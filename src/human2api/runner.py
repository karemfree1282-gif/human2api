"""Main Workflow Execution Runner supporting Real Chromium Browser, Desktop Accessibility, and Android Companion."""

from __future__ import annotations

import os
import pathlib
import socket
import re
import time
import urllib.parse
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from human2api.contracts import (
    StepExecutionRecord,
    WorkflowRunReport,
    redact_secrets,
    safe_resolve_user_path,
    validate_url_against_policy,
)
from human2api.execution import (
    AssertionFailureError,
    CancellationToken,
    WorkflowCancelledError,
    check_write_approval,
    evaluate_assertion,
    resolve_step_parameters,
)
from human2api.healing import SelfHealingEngine, UIElementCandidate
from human2api.models import AssertionSpec, Workflow, WorkflowStep
from human2api.vault import SecretVault


def normalize_loopback_url_for_chromium(url: str) -> str:
    """Rewrite http://127.0.0.1 or http://localhost to http://127.0.0.2 when Chromium policy blocks 127.0.0.1."""
    if not url:
        return url
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or parsed.hostname not in ("127.0.0.1", "localhost"):
        return url
    # Do not blindly redirect to .2: an app bound only to .1 becomes unreachable.
    # The alternate loopback is useful only when it actually hosts this port.
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    def listening(host: str) -> bool:
        try:
            with socket.create_connection((host, port), timeout=0.12):
                return True
        except OSError:
            return False
    if listening(parsed.hostname) or not listening("127.0.0.2"):
        return url
    replacement = parsed._replace(netloc=f"127.0.0.2:{port}")
    return urllib.parse.urlunparse(replacement)


class ChromiumBrowserSession:
    """Real Chromium browser session powered by Selenium WebDriver (or Playwright if requested) with full support for:
    - Multi-tabs (open_tab, switch_tab, close_tab)
    - Nested iframes (framePath)
    - Safe file uploads & downloads
    - Strict network/host policy enforcement
    - DOM snapshot extraction for 4-tier Self-Healing
    """

    def __init__(
        self,
        workflow: Workflow,
        workspace_dir: Optional[pathlib.Path] = None,
        headless: bool = True,
        rewrite_loopback: bool = True,
    ) -> None:
        self.workflow = workflow
        self.workspace_dir = (workspace_dir or pathlib.Path.cwd()).resolve()
        self.downloads_dir = self.workspace_dir / "downloads"
        self.uploads_dir = self.workspace_dir / "uploads"
        self.headless = headless
        self.rewrite_loopback = rewrite_loopback
        self.driver = None

    def start(self) -> None:
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        # Honor an explicit choice; otherwise use Selenium if it can start,
        # falling back to Playwright rather than failing with a raw ImportError.
        preferred = os.environ.get("H2A_BROWSER_ENGINE", "auto").lower()
        if preferred not in ("auto", "selenium", "playwright"):
            raise ValueError("H2A_BROWSER_ENGINE must be auto, selenium, or playwright")
        selenium_error = None
        if preferred == "playwright":
            from human2api.playwright_driver import PlaywrightDriver
            self.driver = PlaywrightDriver(self.downloads_dir, headless=self.headless)
            self._engine = "playwright"
            return
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
        except ImportError as exc:
            selenium_error = exc
            if preferred == "selenium":
                raise RuntimeError('Selenium is not installed. Run: python -m pip install -e ".[browser]"') from exc
        if selenium_error is not None:
            from human2api.playwright_driver import PlaywrightDriver
            self.driver = PlaywrightDriver(self.downloads_dir, headless=self.headless)
            self._engine = "playwright"
            return
        opts = Options()
        if self.headless:
            opts.add_argument("--headless=new")
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--window-size=1280,900")
        prefs = {
            "download.default_directory": str(self.downloads_dir),
            "download.prompt_for_download": False,
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
        }
        opts.add_experimental_option("prefs", prefs)
        try:
            self.driver = webdriver.Chrome(options=opts)
            self._engine = "selenium"
            self.driver.set_page_load_timeout(15)
        except Exception as exc:
            if preferred == "selenium":
                raise RuntimeError(f"ChromeDriver failed to launch: {exc}") from exc
            from human2api.playwright_driver import PlaywrightDriver
            self.driver = PlaywrightDriver(self.downloads_dir, headless=self.headless)
            self._engine = "playwright"

    def stop(self) -> None:
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None

    def _enter_frames(self, frame_path: List[str]) -> None:
        if self.driver is None:
            return
        self.driver.switch_to.default_content()
        for frame_sel in frame_path:
            el = self._find_raw_element(frame_sel)
            if el is None:
                raise RuntimeError(f"Unable to locate iframe in framePath: {frame_sel!r}")
            self.driver.switch_to.frame(el)

    def _find_raw_element(self, selector: str):
        if self.driver is None or not selector:
            return None
        matches = self._find_raw_elements(selector)
        return matches[0] if len(matches) == 1 else None

    def _find_raw_elements(self, selector: str) -> List[Any]:
        if self.driver is None or not selector:
            return []
        sel = selector.strip()
        try:
            if sel.startswith("//") or sel.startswith("(//"):
                return self.driver.find_elements("xpath", sel)
            if sel.startswith("role="):
                # Parse role=button[name="Submit"]
                m = re.match(r'^role=([a-zA-Z0-9_-]+)(?:\[name="([^"]+)"\])?$', sel)
                if m:
                    role_val, name_val = m.group(1), m.group(2)
                    if getattr(self, "_engine", "selenium") == "playwright":
                        return self.driver.find_by_role(role_val, name_val or "")
                    js = """
                    const role = arguments[0].toLowerCase();
                    const name = (arguments[1] || "").toLowerCase();
                    const all = Array.from(document.querySelectorAll("button, a, input, select, textarea, [role]"));
                    return all.filter(el => {
                      const tag = el.tagName.toLowerCase();
                      const r = (el.getAttribute("role") || (tag === "button" ? "button" : (tag === "a" ? "link" : (tag === "input" || tag === "textarea" ? "textbox" : tag)))).toLowerCase();
                      if (r !== role) return false;
                      if (!name) return true;
                      const label = (el.innerText || el.value || el.getAttribute("aria-label") || el.getAttribute("placeholder") || "").trim().toLowerCase();
                      return label.includes(name);
                    });
                    """
                    return self.driver.execute_script(js, role_val, name_val or "") or []
            return self.driver.find_elements("css selector", sel)
        except Exception:
            return []

    def snapshot_candidates(self) -> List[UIElementCandidate]:
        if self.driver is None:
            return []
        js = """
        const nodes = Array.from(document.querySelectorAll("button, a, input, select, textarea, [role], [data-testid], [id]"));
        return nodes.map((el, idx) => {
          const tag = (el.tagName || "").toLowerCase();
          const type = (el.getAttribute("type") || "").toLowerCase();
          const role = el.getAttribute("role") || (
            tag === "button" || type === "submit" || type === "button" ? "button" :
            tag === "a" ? "link" :
            tag === "select" ? "combobox" :
            (tag === "input" || tag === "textarea") ? "textbox" : tag
          );
          let selector = tag;
          if (el.getAttribute("data-testid")) selector = `[data-testid="${el.getAttribute("data-testid")}"]`;
          else if (el.id) selector = `#${el.id}`;
          else if (el.getAttribute("name")) selector = `${tag}[name="${el.getAttribute("name")}"]`;
          else if (el.getAttribute("aria-label")) selector = `[aria-label="${el.getAttribute("aria-label")}"]`;
          const rect = el.getBoundingClientRect();
          const style = window.getComputedStyle(el);
          const visible = style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
          let labelText = "";
          if (el.id) {
            const lbl = document.querySelector(`label[for="${el.id}"]`);
            if (lbl) labelText = lbl.innerText;
          }
          const name = (el.getAttribute("aria-label") || labelText || el.innerText || el.getAttribute("placeholder") || el.getAttribute("title") || "").trim();
          el.setAttribute("data-h2a-cand-id", `cand_${idx}`);
          return {
            candidate_id: `cand_${idx}`,
            selector: selector,
            role: role,
            name: name,
            automation_id: el.getAttribute("data-testid") || el.id || "",
            resource_id: el.getAttribute("name") || "",
            placeholder: el.getAttribute("placeholder") || "",
            tag_name: tag,
            visible: visible,
            enabled: !el.disabled,
            is_password: type === "password",
            host_or_package: window.location.hostname || ""
          };
        });
        """
        try:
            raw_list = self.driver.execute_script(js) or []
            return [UIElementCandidate(**item) for item in raw_list if isinstance(item, dict)]
        except Exception:
            return []


class WorkflowRunner:
    """Executes workflows across Browser, Desktop, and Android targets with 4-tier self-healing and assertions."""

    def __init__(
        self,
        vault: Optional[SecretVault] = None,
        workspace_dir: Optional[pathlib.Path] = None,
        desktop_adapter: Optional[Any] = None,
        android_adapter: Optional[Any] = None,
        ai_advisor: Optional[Callable[[Dict[str, Any], List[Dict[str, Any]]], Optional[str]]] = None,
        step_observer: Optional[Callable[[StepExecutionRecord], None]] = None,
    ) -> None:
        self.vault = vault
        self.workspace_dir = (workspace_dir or pathlib.Path.cwd()).resolve()
        self.desktop_adapter = desktop_adapter
        self.android_adapter = android_adapter
        self.ai_advisor = ai_advisor
        self.step_observer = step_observer

    def run(
        self,
        workflow: Workflow,
        inputs: Optional[Dict[str, Any]] = None,
        allow_write: bool = False,
        cancel_token: Optional[CancellationToken] = None,
        headless: bool = True,
    ) -> WorkflowRunReport:
        start_ts = time.perf_counter()
        token = cancel_token or CancellationToken()
        runtime_inputs = dict(inputs or {})
        secrets_known: Set[str] = set()
        if self.vault and self.vault.is_unlocked():
            secrets_known.update(self.vault.all_secret_values())
        for k, spec in workflow.inputs.items():
            if (spec.sensitive or spec.type == "secret") and k in runtime_inputs and runtime_inputs[k]:
                secrets_known.add(str(runtime_inputs[k]))

        try:
            check_write_approval(workflow, allow_write=allow_write)
            token.check()
        except Exception as exc:
            return WorkflowRunReport(
                workflow_name=workflow.name,
                target=workflow.target,
                status="cancelled" if isinstance(exc, WorkflowCancelledError) else "failed",
                duration_ms=(time.perf_counter() - start_ts) * 1000.0,
                error=redact_secrets(str(exc), secrets_known),
            )

        if workflow.target in ("browser", "web"):
            return self._run_browser(workflow, runtime_inputs, secrets_known, token, headless, start_ts)
        elif workflow.target in ("desktop", "windows-uia", "macos-ax", "linux-atspi"):
            return self._run_desktop(workflow, runtime_inputs, secrets_known, token, start_ts)
        elif workflow.target in ("android", "android-companion"):
            return self._run_android(workflow, runtime_inputs, secrets_known, token, start_ts)
        else:
            return WorkflowRunReport(
                workflow_name=workflow.name,
                target=workflow.target,
                status="failed",
                duration_ms=(time.perf_counter() - start_ts) * 1000.0,
                error=f"Unsupported target: {workflow.target}",
            )

    def _run_browser(
        self,
        workflow: Workflow,
        runtime_inputs: Dict[str, Any],
        secrets_known: Set[str],
        token: CancellationToken,
        headless: bool,
        start_ts: float,
    ) -> WorkflowRunReport:
        session = ChromiumBrowserSession(workflow, workspace_dir=self.workspace_dir, headless=headless)
        token.register_callback(session.stop)
        healer = SelfHealingEngine(config=workflow.healing, ai_advisor=self.ai_advisor)
        step_records: List[StepExecutionRecord] = []
        healing_events: List[Dict[str, Any]] = []
        outputs: Dict[str, Any] = {}
        assertions_passed = 0
        assertions_failed = 0

        try:
            session.start()
            driver = session.driver
            assert driver is not None

            for idx, step in enumerate(workflow.steps):
                token.check()
                step_start = time.perf_counter()
                step_id = step.id or f"step_{idx + 1}"
                attempts = max(1, step.retries + 1)
                already_dispatched_write = False
                last_err: Optional[Exception] = None

                for attempt in range(attempts):
                    token.check()
                    try:
                        session._enter_frames(step.framePath)
                        action = step.action

                        if action in ("goto", "navigate"):
                            raw_url, used_sec = resolve_step_parameters(step.url, workflow, runtime_inputs, self.vault)
                            secrets_known.update(used_sec)
                            if not raw_url:
                                raise ValueError(f"Step {step_id} missing URL.")
                            validate_url_against_policy(raw_url, workflow.allowedHosts, workflow.networkPolicy)
                            nav_url = normalize_loopback_url_for_chromium(raw_url)
                            driver.get(nav_url)
                            # Verify post-redirect URL still obeys allowedHosts
                            current_url = driver.current_url
                            if current_url and current_url != "about:blank":
                                validate_url_against_policy(current_url, workflow.allowedHosts, workflow.networkPolicy)
                            rec = StepExecutionRecord(
                                step_id=step_id,
                                action=action,
                                status="passed",
                                duration_ms=(time.perf_counter() - step_start) * 1000.0,
                            )
                            step_records.append(rec)
                            if self.step_observer:
                                self.step_observer(rec)
                            last_err = None
                            break

                        if action == "open_tab":
                            raw_url, used_sec = resolve_step_parameters(step.url or "about:blank", workflow, runtime_inputs, self.vault)
                            secrets_known.update(used_sec)
                            if raw_url and raw_url != "about:blank":
                                validate_url_against_policy(raw_url, workflow.allowedHosts, workflow.networkPolicy)
                                raw_url = normalize_loopback_url_for_chromium(raw_url)
                            driver.switch_to.new_window("tab")
                            if raw_url and raw_url != "about:blank":
                                driver.get(raw_url)
                            rec = StepExecutionRecord(
                                step_id=step_id,
                                action=action,
                                status="passed",
                                duration_ms=(time.perf_counter() - step_start) * 1000.0,
                            )
                            step_records.append(rec)
                            if self.step_observer:
                                self.step_observer(rec)
                            last_err = None
                            break

                        if action == "switch_tab":
                            handles = driver.window_handles
                            if step.tabIndex is not None:
                                if step.tabIndex < 0 or step.tabIndex >= len(handles):
                                    raise RuntimeError(f"Tab index {step.tabIndex} out of range (total={len(handles)}).")
                                driver.switch_to.window(handles[step.tabIndex])
                            elif step.tabTitle:
                                matched_tab = False
                                for h in handles:
                                    driver.switch_to.window(h)
                                    if step.tabTitle.lower() in (driver.title or "").lower():
                                        matched_tab = True
                                        break
                                if not matched_tab:
                                    raise RuntimeError(f"No open tab matching title {step.tabTitle!r}.")
                            rec = StepExecutionRecord(
                                step_id=step_id,
                                action=action,
                                status="passed",
                                duration_ms=(time.perf_counter() - step_start) * 1000.0,
                            )
                            step_records.append(rec)
                            if self.step_observer:
                                self.step_observer(rec)
                            last_err = None
                            break

                        if action == "close_tab":
                            handles = list(driver.window_handles)
                            if len(handles) > 1:
                                cur = driver.current_window_handle
                                remaining = [h for h in handles if h != cur]
                                try:
                                    driver.execute_cdp_cmd("Target.closeTarget", {"targetId": cur})
                                except Exception:
                                    pass
                                driver.switch_to.window(remaining[-1])
                            rec = StepExecutionRecord(
                                step_id=step_id,
                                action=action,
                                status="passed",
                                duration_ms=(time.perf_counter() - step_start) * 1000.0,
                            )
                            step_records.append(rec)
                            if self.step_observer:
                                self.step_observer(rec)
                            last_err = None
                            break

                        if action == "scroll":
                            driver.execute_script("window.scrollBy(arguments[0], arguments[1]);", step.deltaX, step.deltaY)
                            rec = StepExecutionRecord(
                                step_id=step_id,
                                action=action,
                                status="passed",
                                duration_ms=(time.perf_counter() - step_start) * 1000.0,
                            )
                            step_records.append(rec)
                            if self.step_observer:
                                self.step_observer(rec)
                            last_err = None
                            break

                        if action == "assert_url":
                            exp_val, used_sec = resolve_step_parameters(str(step.expected or ""), workflow, runtime_inputs, self.vault)
                            secrets_known.update(used_sec)
                            evaluate_assertion(
                                AssertionSpec(type="assert_url", expected=exp_val, match=step.match),
                                driver.current_url,
                            )
                            assertions_passed += 1
                            rec = StepExecutionRecord(
                                step_id=step_id,
                                action=action,
                                status="passed",
                                duration_ms=(time.perf_counter() - step_start) * 1000.0,
                            )
                            step_records.append(rec)
                            if self.step_observer:
                                self.step_observer(rec)
                            last_err = None
                            break

                        # Resolve target element using 4-tier SelfHealingEngine
                        candidates = session.snapshot_candidates()

                        def _dom_matcher(sel: str) -> List[UIElementCandidate]:
                            els = session._find_raw_elements(sel)
                            out_cands = []
                            for el in els:
                                cid = el.get_attribute("data-h2a-cand-id")
                                found = next((c for c in candidates if c.candidate_id == cid), None)
                                if found:
                                    out_cands.append(found)
                                else:
                                    out_cands.append(
                                        UIElementCandidate(
                                            candidate_id=cid or f"raw_{len(out_cands)}",
                                            selector=sel,
                                            role=el.get_attribute("role") or el.tag_name,
                                            name=(el.text or el.get_attribute("aria-label") or "").strip(),
                                            visible=el.is_displayed(),
                                            enabled=el.is_enabled(),
                                            host_or_package=urllib.parse.urlparse(driver.current_url).hostname or "",
                                        )
                                    )
                            return out_cands

                        resolution = healer.resolve(
                            step=step,
                            candidates=candidates,
                            primary_matcher=_dom_matcher,
                            allowed_scopes=workflow.allowedHosts,
                            already_executed_write=already_dispatched_write,
                        )
                        if not resolution.resolved or not resolution.selector:
                            raise RuntimeError(f"Step {step_id} ({action}) element resolution failed: {resolution.reason}")

                        if resolution.tier > 1:
                            healing_events.append(
                                {
                                    "step_id": step_id,
                                    "original_selector": step.selector,
                                    "healed_selector": resolution.selector,
                                    "tier": resolution.tier,
                                    "confidence": resolution.confidence,
                                    "reason": resolution.reason,
                                }
                            )

                        # Locate actual WebElement
                        if resolution.candidate_id and resolution.candidate_id.startswith("cand_"):
                            raw_els = session._find_raw_elements(f'[data-h2a-cand-id="{resolution.candidate_id}"]')
                        else:
                            raw_els = session._find_raw_elements(resolution.selector)
                        if not raw_els:
                            raw_els = session._find_raw_elements(resolution.selector)
                        if len(raw_els) != 1:
                            raise RuntimeError(
                                f"Resolved selector {resolution.selector!r} matched {len(raw_els)} elements (expected 1)."
                            )
                        target_el = raw_els[0]

                        extracted: Any = None
                        if action == "click":
                            if step.isWriteAction or not step.idempotent:
                                already_dispatched_write = True
                            # Check if link points to disallowed cross-origin host before clicking
                            href = target_el.get_attribute("href")
                            if href and not href.startswith("#") and not href.startswith("javascript:"):
                                joined = urllib.parse.urljoin(driver.current_url, href)
                                validate_url_against_policy(joined, workflow.allowedHosts, workflow.networkPolicy)
                            target_el.click()
                            # Re-verify current_url after click
                            if driver.current_url and driver.current_url != "about:blank":
                                validate_url_against_policy(driver.current_url, workflow.allowedHosts, workflow.networkPolicy)

                        elif action in ("type", "type_text", "fill"):
                            raw_text = step.text if step.text is not None else str(step.value or "")
                            text_val, used_sec = resolve_step_parameters(raw_text, workflow, runtime_inputs, self.vault)
                            secrets_known.update(used_sec)
                            if step.isWriteAction or not step.idempotent:
                                already_dispatched_write = True
                            target_el.clear()
                            target_el.send_keys(text_val or "")

                        elif action == "select":
                            raw_val = str(step.value if step.value is not None else (step.text or ""))
                            val_resolved, used_sec = resolve_step_parameters(raw_val, workflow, runtime_inputs, self.vault)
                            secrets_known.update(used_sec)
                            already_dispatched_write = True
                            if hasattr(target_el, "select_by_value"):
                                target_el.select_by_value(val_resolved or "")
                            else:
                                from selenium.webdriver.support.ui import Select
                                sel_obj = Select(target_el)
                                try:
                                    sel_obj.select_by_value(val_resolved or "")
                                except Exception:
                                    sel_obj.select_by_visible_text(val_resolved or "")

                        elif action == "upload_file":
                            raw_path, used_sec = resolve_step_parameters(step.filePath, workflow, runtime_inputs, self.vault)
                            secrets_known.update(used_sec)
                            safe_file = safe_resolve_user_path(session.uploads_dir, raw_path or "")
                            if not safe_file.exists():
                                raise FileNotFoundError(f"Upload file does not exist inside approved uploads dir: {safe_file.name}")
                            already_dispatched_write = True
                            target_el.send_keys(str(safe_file))

                        elif action == "download_file":
                            target_el.click()
                            if step.downloadName:
                                safe_dl = safe_resolve_user_path(session.downloads_dir, step.downloadName)
                                extracted = str(safe_dl.name)
                                outputs[step_id] = extracted

                        elif action == "extract_text":
                            extracted = (target_el.text or target_el.get_attribute("value") or "").strip()
                            outputs[step.variable or step_id] = extracted

                        elif action in ("assert_text", "assert_visible", "assert_value"):
                            exp_val, used_sec = resolve_step_parameters(
                                str(step.expected) if step.expected is not None else None,
                                workflow,
                                runtime_inputs,
                                self.vault,
                            )
                            secrets_known.update(used_sec)
                            actual = (
                                target_el.is_displayed()
                                if action == "assert_visible"
                                else (
                                    target_el.get_attribute("value")
                                    if action == "assert_value"
                                    else (target_el.text or target_el.get_attribute("value") or "")
                                )
                            )
                            evaluate_assertion(
                                AssertionSpec(type=action, selector=resolution.selector, expected=exp_val, match=step.match),
                                actual,
                            )
                            assertions_passed += 1

                        rec = StepExecutionRecord(
                            step_id=step_id,
                            action=action,
                            status="healed" if resolution.tier > 1 else "passed",
                            duration_ms=(time.perf_counter() - step_start) * 1000.0,
                            selector_used=resolution.selector,
                            healing_tier=resolution.tier,
                            extracted_value=extracted,
                        )
                        step_records.append(rec)
                        if self.step_observer:
                            self.step_observer(rec)
                        last_err = None
                        break

                    except Exception as exc:
                        last_err = exc
                        if isinstance(exc, (PermissionError, WorkflowCancelledError, AssertionFailureError)):
                            break
                        if already_dispatched_write and (step.isWriteAction or not step.idempotent):
                            # Never retry a write step that already dispatched
                            break
                        if attempt + 1 < attempts:
                            time.sleep(step.retryDelayMs / 1000.0)

                if last_err is not None:
                    if isinstance(last_err, AssertionFailureError):
                        assertions_failed += 1
                    rec = StepExecutionRecord(
                        step_id=step_id,
                        action=step.action,
                        status="cancelled" if isinstance(last_err, WorkflowCancelledError) else "failed",
                        duration_ms=(time.perf_counter() - step_start) * 1000.0,
                        error=redact_secrets(str(last_err), secrets_known),
                    )
                    step_records.append(rec)
                    if self.step_observer:
                        self.step_observer(rec)
                    raise last_err

            # Evaluate workflow-level post-assertions
            session._enter_frames([])
            for aspec in workflow.assertions:
                token.check()
                exp_val, used_sec = resolve_step_parameters(
                    str(aspec.expected) if aspec.expected is not None else None,
                    workflow,
                    runtime_inputs,
                    self.vault,
                )
                secrets_known.update(used_sec)
                effective_spec = AssertionSpec(
                    type=aspec.type,
                    selector=aspec.selector,
                    expected=exp_val if exp_val is not None else aspec.expected,
                    match=aspec.match,
                    timeoutMs=aspec.timeoutMs,
                )
                if aspec.type == "assert_url":
                    actual = driver.current_url
                elif aspec.type == "assert_title":
                    actual = driver.title
                elif aspec.type == "assert_count":
                    actual = len(session._find_raw_elements(aspec.selector or ""))
                else:
                    el = session._find_raw_element(aspec.selector or "")
                    if el is None:
                        if aspec.type == "assert_visible":
                            actual = False
                        else:
                            assertions_failed += 1
                            raise AssertionFailureError(f"Post-assertion selector {aspec.selector!r} not found.")
                    else:
                        actual = (
                            el.is_displayed()
                            if aspec.type == "assert_visible"
                            else (
                                el.get_attribute("value")
                                if aspec.type == "assert_value"
                                else (el.text or el.get_attribute("value") or "")
                            )
                        )
                try:
                    evaluate_assertion(effective_spec, actual)
                    assertions_passed += 1
                except AssertionFailureError:
                    assertions_failed += 1
                    raise

            return WorkflowRunReport(
                workflow_name=workflow.name,
                target=workflow.target,
                status="passed",
                duration_ms=(time.perf_counter() - start_ts) * 1000.0,
                steps=step_records,
                assertions_passed=assertions_passed,
                assertions_failed=assertions_failed,
                healing_events=healing_events,
                outputs=outputs,
            )

        except Exception as exc:
            status = "cancelled" if isinstance(exc, WorkflowCancelledError) else "failed"
            return WorkflowRunReport(
                workflow_name=workflow.name,
                target=workflow.target,
                status=status,
                duration_ms=(time.perf_counter() - start_ts) * 1000.0,
                steps=step_records,
                assertions_passed=assertions_passed,
                assertions_failed=assertions_failed,
                healing_events=healing_events,
                outputs=outputs,
                error=redact_secrets(str(exc), secrets_known),
            )
        finally:
            session.stop()

    def _run_desktop(
        self,
        workflow: Workflow,
        runtime_inputs: Dict[str, Any],
        secrets_known: Set[str],
        token: CancellationToken,
        start_ts: float,
    ) -> WorkflowRunReport:
        from human2api.desktop import get_desktop_adapter

        try:
            adapter = self.desktop_adapter or get_desktop_adapter(workflow.target)
        except (RuntimeError, ImportError, OSError) as exc:
            return WorkflowRunReport(
                workflow_name=workflow.name, target=workflow.target,
                status="failed", duration_ms=(time.perf_counter() - start_ts) * 1000.0,
                error=f"Desktop runtime unavailable: {exc}",
            )
        return adapter.execute_workflow(
            workflow=workflow,
            runtime_inputs=runtime_inputs,
            vault=self.vault,
            secrets_known=secrets_known,
            cancel_token=token,
            ai_advisor=self.ai_advisor,
            step_observer=self.step_observer,
            start_ts=start_ts,
        )

    def _run_android(
        self,
        workflow: Workflow,
        runtime_inputs: Dict[str, Any],
        secrets_known: Set[str],
        token: CancellationToken,
        start_ts: float,
    ) -> WorkflowRunReport:
        from human2api.android import LiveAndroidCompanionClient

        try:
            adapter = self.android_adapter or LiveAndroidCompanionClient()
        except (PermissionError, RuntimeError, ValueError) as exc:
            return WorkflowRunReport(
                workflow_name=workflow.name, target=workflow.target, status="failed",
                duration_ms=(time.perf_counter() - start_ts) * 1000.0,
                error=f"Android connection is not ready: {exc}",
            )
        return adapter.execute_workflow(
            workflow=workflow,
            runtime_inputs=runtime_inputs,
            vault=self.vault,
            secrets_known=secrets_known,
            cancel_token=token,
            ai_advisor=self.ai_advisor,
            step_observer=self.step_observer,
            start_ts=start_ts,
        )
