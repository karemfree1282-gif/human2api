"""Multi-target Workflow Recorder with privacy redaction, secret variable substitution, and stable selector generation."""

from __future__ import annotations

import re
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

from human2api.contracts import is_sensitive_field_name
from human2api.models import (
    AssertionSpec,
    HealingConfig,
    InputSpec,
    SelectorCandidate,
    Workflow,
    WorkflowStep,
)


def _slugify_var_name(raw: str, prefix: str = "field", index: int = 1) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]+", "_", (raw or "").strip()).strip("_").lower()
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"{prefix}_{cleaned}" if cleaned else f"{prefix}_{index}"
    return cleaned[:48]


def build_resilient_selectors(event: Dict[str, Any]) -> Tuple[str, List[SelectorCandidate]]:
    """Build a stable primary selector and ranked fallback selectors from a recorded UI/DOM event."""
    candidates: List[SelectorCandidate] = []
    testid = event.get("data_testid") or event.get("testid")
    el_id = event.get("id")
    aria_label = event.get("aria_label")
    name_attr = event.get("name_attr")
    role = event.get("role") or ""
    accessible_name = event.get("accessible_name") or event.get("text") or aria_label or ""
    placeholder = event.get("placeholder")
    automation_id = event.get("automation_id")
    resource_id = event.get("resource_id")
    css = event.get("selector") or event.get("css")
    xpath = event.get("xpath")

    if testid:
        candidates.append(
            SelectorCandidate(
                strategy="testid",
                value=f'[data-testid="{testid}"]',
                role=role or None,
                name=accessible_name or None,
                confidence=0.99,
            )
        )
    if automation_id:
        candidates.append(
            SelectorCandidate(
                strategy="automation_id",
                value=str(automation_id),
                role=role or None,
                name=accessible_name or None,
                confidence=0.98,
            )
        )
    if resource_id:
        candidates.append(
            SelectorCandidate(
                strategy="resource_id",
                value=str(resource_id),
                role=role or None,
                name=accessible_name or None,
                confidence=0.98,
            )
        )
    if el_id and not re.search(r"\d{5,}", str(el_id)):
        candidates.append(
            SelectorCandidate(
                strategy="id",
                value=f"#{el_id}",
                role=role or None,
                name=accessible_name or None,
                confidence=0.96,
            )
        )
    if aria_label:
        candidates.append(
            SelectorCandidate(
                strategy="aria-label",
                value=f'[aria-label="{aria_label}"]',
                role=role or None,
                name=aria_label,
                confidence=0.94,
            )
        )
    if name_attr:
        candidates.append(
            SelectorCandidate(
                strategy="name",
                value=f'[name="{name_attr}"]',
                role=role or None,
                name=accessible_name or None,
                confidence=0.92,
            )
        )
    if placeholder:
        candidates.append(
            SelectorCandidate(
                strategy="placeholder",
                value=f'[placeholder="{placeholder}"]',
                role=role or None,
                name=placeholder,
                confidence=0.89,
            )
        )
    if role and accessible_name:
        candidates.append(
            SelectorCandidate(
                strategy="role",
                value=f'role={role}[name="{accessible_name}"]',
                role=role,
                name=accessible_name,
                confidence=0.88,
            )
        )
    if css:
        candidates.append(
            SelectorCandidate(
                strategy="css",
                value=str(css),
                role=role or None,
                name=accessible_name or None,
                confidence=0.82,
            )
        )
    if xpath:
        candidates.append(
            SelectorCandidate(
                strategy="xpath",
                value=str(xpath),
                role=role or None,
                name=accessible_name or None,
                confidence=0.75,
            )
        )

    if not candidates:
        fallback_css = event.get("tag_name") or "body"
        return str(fallback_css), []

    primary = candidates[0].value
    # Deduplicate fallbacks while preserving order
    seen = {primary}
    fallbacks: List[SelectorCandidate] = []
    for cand in candidates[1:]:
        if cand.value not in seen:
            seen.add(cand.value)
            fallbacks.append(cand)
    return primary, fallbacks


class WorkflowRecorder:
    """Converts raw user interaction events into a privacy-safe, parameterized Workflow."""

    def __init__(
        self,
        name: str,
        target: str = "browser",
        network_policy: str = "strict",
    ) -> None:
        self.name = name
        self.target = target
        self.network_policy = network_policy
        self.events: List[Dict[str, Any]] = []

    def record_event(self, event: Dict[str, Any]) -> None:
        self.events.append(dict(event))

    def compile_workflow(self) -> Workflow:
        steps: List[WorkflowStep] = []
        inputs: Dict[str, InputSpec] = {}
        allowed_hosts: List[str] = []
        allowed_apps: List[str] = []
        allowed_packages: List[str] = []
        assertions: List[AssertionSpec] = []
        has_write = False

        for idx, ev in enumerate(self.events):
            action = str(ev.get("action") or ev.get("type") or "click").lower().strip()
            if action == "input":
                action = "type"

            url = ev.get("url")
            if url:
                parsed = urllib.parse.urlparse(str(url))
                if parsed.hostname and parsed.hostname not in allowed_hosts:
                    allowed_hosts.append(parsed.hostname)

            app_name = ev.get("app_name") or ev.get("windowTitle")
            if app_name and app_name not in allowed_apps and self.target in ("desktop", "windows-uia", "macos-ax", "linux-atspi"):
                allowed_apps.append(str(app_name))

            pkg = ev.get("packageName") or ev.get("package")
            if pkg and pkg not in allowed_packages:
                allowed_packages.append(str(pkg))

            if action in ("goto", "navigate"):
                steps.append(
                    WorkflowStep(
                        id=f"step_{idx + 1}",
                        action="goto",
                        url=str(url or ""),
                        tabIndex=ev.get("tabIndex"),
                    )
                )
                continue

            if action in ("switch_tab", "open_tab", "close_tab"):
                steps.append(
                    WorkflowStep(
                        id=f"step_{idx + 1}",
                        action=action,
                        tabIndex=ev.get("tabIndex"),
                        tabTitle=ev.get("tabTitle"),
                        url=ev.get("url"),
                    )
                )
                continue

            if action == "scroll":
                primary_sel, fallbacks = build_resilient_selectors(ev) if ev.get("selector") or ev.get("id") else (None, [])
                steps.append(
                    WorkflowStep(
                        id=f"step_{idx + 1}",
                        action="scroll",
                        selector=primary_sel,
                        fallbackSelectors=fallbacks,
                        deltaX=float(ev.get("deltaX", 0)),
                        deltaY=float(ev.get("deltaY", 300)),
                        framePath=list(ev.get("framePath") or []),
                    )
                )
                continue

            primary_sel, fallbacks = build_resilient_selectors(ev)
            role = ev.get("role")
            acc_name = ev.get("accessible_name") or ev.get("aria_label") or ev.get("label") or ev.get("text")
            auto_id = ev.get("automation_id") or ev.get("id")
            res_id = ev.get("resource_id")
            frame_path = list(ev.get("framePath") or [])

            if action in ("type", "type_text", "fill", "select"):
                has_write = True
                field_hint = (
                    ev.get("name_attr")
                    or ev.get("id")
                    or ev.get("aria_label")
                    or ev.get("placeholder")
                    or ev.get("automation_id")
                    or f"input_{idx + 1}"
                )
                is_secret = bool(
                    ev.get("is_password")
                    or str(ev.get("input_type", "")).lower() == "password"
                    or "password" in str(ev.get("autocomplete", "")).lower()
                    or ev.get("sensitive")
                    or is_sensitive_field_name(str(field_hint))
                    or is_sensitive_field_name(str(acc_name or ""))
                )
                var_name = _slugify_var_name(str(field_hint), prefix="secret" if is_secret else "param", index=idx + 1)

                if is_secret:
                    # NEVER store raw password or secret value in workflow steps or input defaults
                    inputs[var_name] = InputSpec(
                        type="secret",
                        description=f"Secret credential for {field_hint}",
                        required=True,
                        sensitive=True,
                        default=None,
                    )
                    step_text = f"${{secret:{var_name}}}"
                else:
                    raw_val = ev.get("value") if ev.get("value") is not None else ev.get("text", "")
                    inputs[var_name] = InputSpec(
                        type="string",
                        description=f"Input value for {field_hint}",
                        required=True,
                        sensitive=False,
                        default=str(raw_val) if raw_val is not None else "",
                    )
                    step_text = f"${{input:{var_name}}}"

                steps.append(
                    WorkflowStep(
                        id=f"step_{idx + 1}",
                        action="select" if action == "select" else ("type_text" if self.target.startswith("android") else "type"),
                        selector=primary_sel,
                        fallbackSelectors=fallbacks,
                        text=step_text if action != "select" else None,
                        value=step_text if action == "select" else None,
                        variable=var_name,
                        sensitive=is_secret,
                        idempotent=not bool(ev.get("submit", False)),
                        isWriteAction=True,
                        framePath=frame_path,
                        role=role,
                        name=acc_name,
                        automationId=auto_id,
                        windowTitle=ev.get("windowTitle"),
                        packageName=pkg,
                        resourceId=res_id,
                        contentDesc=ev.get("content_desc"),
                    )
                )
                continue

            if action == "upload_file":
                has_write = True
                var_name = _slugify_var_name(ev.get("name_attr") or "upload_file", prefix="file", index=idx + 1)
                # Store only basename, never full host user path
                raw_file = str(ev.get("filePath") or ev.get("file_name") or "upload.txt").replace("\\", "/").split("/")[-1]
                inputs[var_name] = InputSpec(
                    type="file",
                    description="Relative file path inside approved workspace upload directory",
                    required=True,
                    sensitive=False,
                    default=raw_file,
                )
                steps.append(
                    WorkflowStep(
                        id=f"step_{idx + 1}",
                        action="upload_file",
                        selector=primary_sel,
                        fallbackSelectors=fallbacks,
                        filePath=f"${{input:{var_name}}}",
                        variable=var_name,
                        idempotent=False,
                        isWriteAction=True,
                        framePath=frame_path,
                        role=role or "button",
                        name=acc_name,
                    )
                )
                continue

            if action in ("assert_text", "assert_visible", "assert_url", "assert_value"):
                assertions.append(
                    AssertionSpec(
                        type=action,
                        selector=primary_sel if action != "assert_url" else None,
                        expected=ev.get("expected") or ev.get("text") or ev.get("url"),
                        match=str(ev.get("match", "contains")),
                    )
                )
                steps.append(
                    WorkflowStep(
                        id=f"step_{idx + 1}",
                        action=action,
                        selector=primary_sel if action != "assert_url" else None,
                        expected=ev.get("expected") or ev.get("text") or ev.get("url"),
                        match=str(ev.get("match", "contains")),
                        framePath=frame_path,
                    )
                )
                continue

            # Default click / interactive step
            is_submit = bool(
                ev.get("submit")
                or str(ev.get("button_type", "")).lower() == "submit"
                or any(
                    w in str(acc_name or "").lower()
                    for w in ("submit", "save", "pay", "confirm", "send", "create", "delete", "إرسال", "حفظ", "تأكيد")
                )
            )
            if is_submit:
                has_write = True
            steps.append(
                WorkflowStep(
                    id=f"step_{idx + 1}",
                    action=action if action in ("click", "double_click", "download_file", "extract_text", "focus_window", "resize_window", "press_key", "back", "home", "swipe") else "click",
                    selector=primary_sel,
                    fallbackSelectors=fallbacks,
                    idempotent=not is_submit,
                    isWriteAction=is_submit,
                    framePath=frame_path,
                    tabIndex=ev.get("tabIndex"),
                    downloadName=ev.get("downloadName"),
                    role=role or "button",
                    name=acc_name,
                    automationId=auto_id,
                    windowTitle=ev.get("windowTitle"),
                    packageName=pkg,
                    resourceId=res_id,
                    contentDesc=ev.get("content_desc"),
                    x=ev.get("x"),
                    y=ev.get("y"),
                )
            )

        return Workflow(
            name=self.name,
            target=self.target,
            mode="write" if has_write else "read",
            networkPolicy=self.network_policy,
            allowedHosts=allowed_hosts,
            allowedApps=allowed_apps,
            allowedPackages=allowed_packages,
            inputs=inputs,
            steps=steps,
            assertions=assertions,
            healing=HealingConfig(enabled=True, maxTier=3, aiConsent=False, aiProvider="none"),
        )


BROWSER_RECORDER_INJECTION_JS = r"""
(() => {
  if (window.__h2aRecorderInstalled) return;
  window.__h2aRecorderInstalled = true;
  window.__h2aRecordedEvents = window.__h2aRecordedEvents || [];

  function computeSelector(el) {
    if (!el || el.nodeType !== 1) return "body";
    if (el.getAttribute("data-testid")) return `[data-testid="${el.getAttribute("data-testid")}"]`;
    if (el.id) return `#${el.id}`;
    if (el.getAttribute("name")) return `${el.tagName.toLowerCase()}[name="${el.getAttribute("name")}"]`;
    if (el.getAttribute("aria-label")) return `[aria-label="${el.getAttribute("aria-label")}"]`;
    return el.tagName.toLowerCase();
  }

  function buildMeta(el, action) {
    const tag = (el.tagName || "").toLowerCase();
    const inputType = (el.getAttribute("type") || "").toLowerCase();
    const isPassword = inputType === "password" || (el.getAttribute("autocomplete") || "").includes("password");
    return {
      action: action,
      url: window.location.href,
      tag_name: tag,
      id: el.id || null,
      data_testid: el.getAttribute("data-testid") || null,
      name_attr: el.getAttribute("name") || null,
      aria_label: el.getAttribute("aria-label") || null,
      placeholder: el.getAttribute("placeholder") || null,
      role: el.getAttribute("role") || (tag === "button" ? "button" : (tag === "a" ? "link" : (tag === "input" || tag === "textarea" ? "textbox" : tag))),
      accessible_name: (el.innerText || el.getAttribute("aria-label") || el.getAttribute("placeholder") || "").trim().slice(0, 80),
      selector: computeSelector(el),
      input_type: inputType,
      is_password: isPassword,
      button_type: (el.getAttribute("type") || "").toLowerCase(),
      value: isPassword ? "[REDACTED]" : (el.value || null)
    };
  }

  document.addEventListener("click", (e) => {
    const el = e.target.closest("button, a, input, select, [role], [data-testid]") || e.target;
    window.__h2aRecordedEvents.push(buildMeta(el, "click"));
  }, true);

  document.addEventListener("change", (e) => {
    const el = e.target;
    if (!el) return;
    const tag = (el.tagName || "").toLowerCase();
    const action = tag === "select" ? "select" : (el.type === "file" ? "upload_file" : "type");
    const ev = buildMeta(el, action);
    if (el.type === "file" && el.files && el.files.length > 0) {
      ev.file_name = el.files[0].name;
      ev.value = null;
    }
    window.__h2aRecordedEvents.push(ev);
  }, true);
})();
"""
