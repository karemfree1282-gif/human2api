"""Execute constrained workflows in a fresh Playwright browser context."""

from __future__ import annotations

import os
import secrets
import shutil
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, Route, expect, sync_playwright

from .models import WorkflowError, secret_redact, template, validate_inputs, validate_workflow

StepHook = Callable[[int, str, str], None]


def launch_browser(playwright: Any, *, headless: bool, browser_path: str | None = None) -> Any:
    """Use the pinned Playwright Chromium where available; optionally use installed Chromium."""
    path = browser_path or os.environ.get("H2A_BROWSER_PATH")
    if path:
        return playwright.chromium.launch(headless=headless, executable_path=path)
    try:
        return playwright.chromium.launch(headless=headless)
    except PlaywrightError as exc:
        binary = shutil.which("chromium") or shutil.which("google-chrome") or shutil.which("chromium-browser")
        if binary:
            return playwright.chromium.launch(headless=headless, executable_path=binary)
        raise WorkflowError("Chromium is not installed; run: python -m playwright install chromium") from exc


def _safe_navigation(url: str, hosts: set[str]) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in hosts or parsed.username or parsed.password:
        raise WorkflowError(f"navigation is outside allowedHosts: {parsed.hostname or '[invalid URL]'}")


def _locator(page: Page, step: dict[str, Any], timeout_ms: int, *, heal: bool = False, ai_heal: bool = False, outputs: dict[str, Any] | None = None) -> Any:
    selectors = [step["selector"], *step.get("alternatives", [])]
    target = page.frame_locator(step["frame"]) if step.get("frame") else page
    last_error = None
    # Wait for the first match, using selectors captured at recording time.
    per_selector = max(250, timeout_ms // len(selectors))
    for selector in selectors:
        try:
            loc = target.locator(selector).first
            loc.wait_for(state="attached", timeout=per_selector)
            return loc
        except PlaywrightError as exc:
            last_error = exc
    if heal:
        from .healing import recover
        suggestion = recover(target, step, ai=ai_heal and not step.get("frame"))
        if suggestion is not None:
            loc, hint = suggestion
            if outputs is not None:
                outputs.setdefault("healing", []).append({"oldSelector": selectors[0], "suggestion": hint, "reviewRequired": True})
            return loc
    raise WorkflowError(f"no matching element for selector {selectors[0]!r}; {str(last_error)[:120]}")


def _run_step(page: Page, step: dict[str, Any], values: dict[str, Any], artifacts: Path, hosts: set[str], outputs: dict[str, Any], *, heal: bool = False, ai_heal: bool = False) -> None:
    action = step["action"]
    timeout_ms = step.get("timeoutMs", 7000)
    if action == "navigate":
        url = template(step["url"], values)
        _safe_navigation(url, hosts)
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        return
    if action == "wait_ms":
        page.wait_for_timeout(step["durationMs"])
        return
    if action == "screenshot":
        filename = step.get("filename", "screenshot.png")
        if not filename.lower().endswith(".png"):
            filename += ".png"
        page.screenshot(path=str(artifacts / filename), full_page=False, timeout=timeout_ms)
        outputs.setdefault("artifacts", []).append(str(artifacts / filename))
        return
    locator = _locator(page, step, timeout_ms, heal=heal, ai_heal=ai_heal, outputs=outputs)
    if action == "click":
        locator.click(timeout=timeout_ms)
    elif action == "fill":
        locator.fill(template(step["value"], values), timeout=timeout_ms)
    elif action == "select":
        locator.select_option(value=template(step["value"], values), timeout=timeout_ms)
    elif action == "check":
        raw = step["checked"]
        checked = template(raw, values) if isinstance(raw, str) else raw
        if isinstance(checked, str):
            if checked not in {"true", "false"}:
                raise WorkflowError("checked must resolve to true or false")
            checked = checked == "true"
        locator.set_checked(checked, timeout=timeout_ms)
    elif action == "press":
        locator.press(step["key"], timeout=timeout_ms)
    elif action == "hover":
        locator.hover(timeout=timeout_ms)
    elif action == "scroll":
        locator.hover(timeout=timeout_ms)
        page.mouse.wheel(0, step.get("delta", 1) * 120)
    elif action == "drag":
        target = page.frame_locator(step["frame"]) if step.get("frame") else page
        locator.drag_to(target.locator(step["targetSelector"]).first, timeout=timeout_ms)
    elif action == "wait":
        locator.wait_for(state="visible", timeout=timeout_ms)
    elif action == "assert_text":
        expect(locator).to_contain_text(template(step["text"], values), timeout=timeout_ms)
    elif action == "extract_text":
        outputs[step["as"]] = locator.inner_text(timeout=timeout_ms)[:10000]
    elif action == "download":
        with page.expect_download(timeout=timeout_ms) as download_info:
            locator.click(timeout=timeout_ms)
        download = download_info.value
        requested = step.get("filename")
        filename = requested or Path(download.suggested_filename).name
        # A remote site controls suggested_filename: never allow path traversal.
        filename = Path(filename.replace("\\", "/")).name
        if not filename or filename.startswith("."):
            filename = "download.bin"
        dest = artifacts / filename
        download.save_as(dest)
        outputs.setdefault("artifacts", []).append(str(dest))
    else:
        raise WorkflowError(f"unsupported action: {action}")


def run_workflow(
    workflow: dict[str, Any],
    provided_inputs: dict[str, Any] | None = None,
    *,
    approve_writes: bool = False,
    headless: bool = True,
    artifacts_dir: str | Path = "runs",
    browser_path: str | None = None,
    on_step: StepHook | None = None,
    heal_selectors: bool = False,
    ai_heal: bool = False,
) -> dict[str, Any]:
    """Run an automation. Write-enabled workflows require an explicit grant.

    Returns only declared outputs and artifact paths. Input field values are not
    included in the output or persisted to history by this runner.
    """
    validate_workflow(workflow)
    values = validate_inputs(workflow, provided_inputs or {})
    if workflow.get("permissions", "write") == "write" and not approve_writes:
        raise WorkflowError("workflow has write permissions; pass --approve (or explicitly approve in the UI)")
    target = workflow.get("target", "browser")
    if ai_heal and not heal_selectors:
        raise WorkflowError("AI healing requires explicit selector-healing consent")
    if ai_heal and target != "browser":
        raise WorkflowError("AI selector healing currently applies to browser workflows only")
    hosts = set(workflow.get("allowedHosts") or ([urlparse(workflow["startUrl"]).hostname] if target == "browser" else []))
    if target == "browser":
        _safe_navigation(workflow["startUrl"], hosts)
    run_id = secrets.token_hex(6)
    artifacts = Path(artifacts_dir).resolve() / f"{workflow['name']}-{run_id}"
    artifacts.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    current_index = 0
    outputs: dict[str, Any] = {}
    try:
        if target in {"desktop", "android"}:
            if target == "desktop":
                from .desktop import execute_desktop
                outputs = execute_desktop(workflow, values, artifacts, on_step=on_step)
            else:
                from .android import execute_android
                outputs = execute_android(workflow, values, artifacts, on_step=on_step)
            return {"ok": True, "workflow": workflow["name"], "target": target, "runId": run_id,
                    "steps": len(workflow["steps"]), "durationMs": round((time.monotonic() - started) * 1000), "outputs": outputs}
        with sync_playwright() as playwright:
            browser = launch_browser(playwright, headless=headless, browser_path=browser_path)
            try:
                context = browser.new_context(accept_downloads=True, service_workers="block")
                blocked_navigations: list[str] = []
                def navigation_gate(route: Route) -> None:
                    if route.request.is_navigation_request():
                        try:
                            _safe_navigation(route.request.url, hosts)
                        except WorkflowError:
                            blocked_navigations.append(urlparse(route.request.url).hostname or "unknown")
                            route.abort(error_code="blockedbyclient")
                            return
                    route.continue_()
                context.route("**/*", navigation_gate)
                page = context.new_page()
                page.set_default_timeout(7000)
                page.goto(workflow["startUrl"], wait_until="domcontentloaded", timeout=20000)
                for current_index, step in enumerate(workflow["steps"], start=1):
                    if on_step:
                        on_step(current_index, step["action"], "running")
                    if step["action"] == "switch_tab":
                        index = step["index"]
                        pages = context.pages
                        if index >= len(pages):
                            raise WorkflowError(f"browser tab {index} does not exist")
                        page = pages[index]
                    else:
                        _run_step(page, step, values, artifacts, hosts, outputs, heal=heal_selectors, ai_heal=ai_heal)
                    if blocked_navigations:
                        raise WorkflowError("browser attempted unauthorized navigation to " + blocked_navigations[0])
                    if on_step:
                        on_step(current_index, step["action"], "passed")
            finally:
                browser.close()
    except (PlaywrightError, WorkflowError, OSError, ValueError) as exc:
        detail = secret_redact(str(exc), workflow, values)
        if on_step:
            on_step(current_index, workflow["steps"][max(0, current_index - 1)]["action"], "failed")
        raise WorkflowError(f"step {current_index or 0} failed: {detail}") from None
    return {
        "ok": True,
        "workflow": workflow["name"],
        "target": "browser",
        "runId": run_id,
        "steps": len(workflow["steps"]),
        "durationMs": round((time.monotonic() - started) * 1000),
        "outputs": outputs,
    }
