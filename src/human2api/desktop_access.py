"""Explicitly scoped native accessibility operations: Windows UIA, macOS AX, Linux AT-SPI.

Queries a unique visible non-password control in a named window. Never records
keystrokes or grants OS permissions. Backend integration needs a real OS session.
"""
from __future__ import annotations

import sys
from typing import Any

from .models import WorkflowError, template


def _desktop() -> Any:
    if sys.platform == "darwin":
        from .native import AXDesktop
        return AXDesktop()
    if sys.platform.startswith("linux"):
        from .native import AtspiDesktop
        return AtspiDesktop()
    if sys.platform != "win32":
        raise WorkflowError("unsupported native accessibility platform")
    try:
        from pywinauto import Desktop
    except ImportError as exc:
        raise WorkflowError("install Windows UI Automation support: pip install 'human2api[accessibility]'") from exc
    return Desktop(backend="uia")


def _element_info(control: Any, field: str) -> str:
    return str(getattr(control.element_info, field, "") or "")


def locate_control(step: dict[str, Any]) -> Any:
    """Fail closed for ambiguous/hidden controls; never choose the first match."""
    windows = [w for w in _desktop().windows(title=step["windowTitle"]) if w.is_visible()]
    if len(windows) != 1:
        raise WorkflowError(f"accessibility window must be unique and visible (matched {len(windows)})")
    window = windows[0]
    candidates = [window, *window.descendants()]
    matching: list[Any] = []
    for item in candidates[:3000]:
        try:
            if not item.is_visible():
                continue
            if step.get("automationId") and _element_info(item, "automation_id") != step["automationId"]:
                continue
            if step.get("name") and _element_info(item, "name") != step["name"]:
                continue
            if step.get("controlType") and _element_info(item, "control_type") != step["controlType"]:
                continue
            if getattr(item.element_info, "is_password", False):
                raise WorkflowError("password inputs are not accessible to workflow selectors")
            matching.append(item)
        except WorkflowError:
            raise
        except (AttributeError, RuntimeError):
            continue
    if len(candidates) > 3000:
        raise WorkflowError("accessibility tree exceeds safe inspection limit")
    if len(matching) != 1:
        raise WorkflowError(f"accessibility selector must match exactly one visible control (matched {len(matching)})")
    return matching[0]


def execute_ui_step(step: dict[str, Any], values: dict[str, Any], *, heal: bool = False, ai: bool = False, audit: list | None = None) -> str | None:
    try:
        item = locate_control(step)
    except WorkflowError as exc:
        # Never heal an ambiguous match, a password input, or an inaccessible window.
        if not heal or "matched 0" not in str(exc) or "window" in str(exc):
            raise
        from .healing import recover_metadata
        suggestion = recover_metadata(step, inspect_window(step["windowTitle"]), ai=ai)
        if suggestion is None:
            raise
        repaired = {k: v for k, v in step.items() if k not in {"name", "automationId", "controlType"}}
        repaired.update({k: v for k, v in suggestion.items() if k in {"name", "automationId", "controlType"} and v})
        item = locate_control(repaired)
        if audit is not None:
            audit.append({"action": step["action"], "recovered": True, "reviewRequired": True})
    action = step["action"]
    if action == "ui_click":
        if not item.is_enabled():
            raise WorkflowError("accessibility control is disabled")
        item.click_input()
    elif action == "ui_fill":
        if not item.is_enabled():
            raise WorkflowError("accessibility control is disabled")
        # UIA ValuePattern handles Unicode and avoids using the user's clipboard.
        try:
            item.set_edit_text(template(step["value"], values))
        except (AttributeError, NotImplementedError) as exc:
            raise WorkflowError("target control does not support native Unicode text input") from exc
    elif action in {"ui_assert_text", "ui_extract_text"}:
        value = item.window_text()
        if action == "ui_assert_text":
            if template(step["text"], values) not in value:
                raise WorkflowError("expected accessibility text not present")
        else:
            return value[:10000]
    else:
        raise WorkflowError("unsupported accessibility action")
    return None


def inspect_window(window_title: str, *, limit: int = 60) -> list[dict[str, str]]:
    if not isinstance(window_title, str) or not 0 < len(window_title) <= 200:
        raise WorkflowError("a window title is required")
    if not 1 <= limit <= 300:
        raise WorkflowError("limit must be between 1 and 300")
    windows = [w for w in _desktop().windows(title=window_title) if w.is_visible()]
    if len(windows) != 1:
        raise WorkflowError("must select exactly one visible window")
    results: list[dict[str, str]] = []
    for item in windows[0].descendants():
        if len(results) >= limit:
            break
        try:
            if not item.is_visible() or getattr(item.element_info, "is_password", False):
                continue
            name = _element_info(item, "name")
            identifier = _element_info(item, "automation_id")
            role = _element_info(item, "control_type")
            if name or identifier:
                # Do not include live control values, Edit content, or screenshots.
                results.append({"windowTitle": window_title, "name": name[:200], "automationId": identifier[:200], "controlType": role[:100]})
        except (AttributeError, RuntimeError):
            continue
    return results


def selector_at_point(x: int, y: int) -> dict[str, str] | None:
    """Best-effort native accessibility selector for a user-clicked point; NEVER captures edit values.

    Caller must explicitly opt in. If neither a stable automation ID nor a unique accessible name is available,
    return None so the recorder can save its ordinary pixel click instead.
    """
    try:
        item = _desktop().from_point(x, y)
        if item is None or not item.is_visible() or getattr(item.element_info, "is_password", False):
            return None
        automation_id = _element_info(item, "automation_id")
        window = item.top_level_parent()
        title = _element_info(window, "name") or window.window_text()
        if not 0 < len(title) <= 200 or len(automation_id) > 200:
            return None
        name = _element_info(item, "name")
        if not automation_id and (not name or len(name) > 200):
            return None
        result = {"action": "ui_click", "windowTitle": title,
                  "controlType": _element_info(item, "control_type")[:200] or "Custom"}
        result.update({"automationId": automation_id} if automation_id else {"name": name})
        locate_control(result)  # Do not record an ambiguous accessible name.
        return result
    except (AttributeError, RuntimeError, WorkflowError, OSError):
        return None
