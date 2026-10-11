"""Opt-in Windows UI Automation selectors for resilient native-app workflows.

This module does not start an accessibility listener or capture keystrokes. It
queries exactly one named window and exactly one named child on demand. Requires
Windows UI Automation (pywinauto); other OSes retain coordinate actions.
"""
from __future__ import annotations

import sys
from typing import Any

from .models import WorkflowError, template


def _desktop() -> Any:
    if sys.platform != "win32":
        raise WorkflowError("native UI Automation selectors require Windows; use coordinate workflows on macOS/Linux")
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


def execute_ui_step(step: dict[str, Any], values: dict[str, Any]) -> str | None:
    item = locate_control(step)
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
            raise WorkflowError("target control does not support UIA text input") from exc
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
    """Best-effort UIA selector for a user-clicked point; NEVER captures edit values.

    Caller must explicitly opt in. If no stable automation ID is available,
    return None so the recorder can save its ordinary pixel click instead.
    """
    try:
        item = _desktop().from_point(x, y)
        if item is None or not item.is_visible() or getattr(item.element_info, "is_password", False):
            return None
        automation_id = _element_info(item, "automation_id")
        window = item.top_level_parent()
        title = window.window_text()
        if not automation_id or not 0 < len(title) <= 200 or len(automation_id) > 200:
            return None
        return {"action": "ui_click", "windowTitle": title, "automationId": automation_id,
                "controlType": _element_info(item, "control_type")[:200] or "Custom"}
    except (AttributeError, RuntimeError, WorkflowError, OSError):
        return None
