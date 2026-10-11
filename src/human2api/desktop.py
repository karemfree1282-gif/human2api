"""Explicit-consent desktop automation for Windows, macOS and Linux.

PyAutoGUI is imported on demand, so headless servers can still serve MCP and
browser workflows. Screenshots remain in the run's private artifacts directory.
The recorder intentionally NEVER captures typed keys or clipboard contents.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from .models import WorkflowError, template
from .execution import RunCancelled, check_cancelled, interruptible_wait, run_step_with_retry


SAFE_KEYS = {"enter", "tab", "esc", "escape", "space", "backspace", "delete", "up", "down", "left", "right", "home", "end", "pageup", "pagedown", "ctrl", "shift", "alt", "command", "win", "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12", "a", "c", "v", "x", "z", "s", "n", "p"}


def _gui() -> Any:
    try:
        import pyautogui
    except ImportError as exc:
        raise WorkflowError("Desktop support requires: pip install 'human2api[desktop]'") from exc
    try:
        pyautogui.FAILSAFE = True  # mouse to upper-left corner to stop
        pyautogui.PAUSE = 0.1
    except Exception as exc:
        raise WorkflowError("desktop cannot access a graphical session") from exc
    return pyautogui


def execute_desktop(workflow: dict[str, Any], values: dict[str, Any], artifacts: Path, on_step: Callable | None = None, *, cancel_event: Any = None) -> dict[str, Any]:
    gui = _gui() if any(step["action"] not in {"ui_click", "ui_fill", "ui_assert_text", "ui_extract_text", "wait_ms"} for step in workflow["steps"]) else None
    outputs: dict[str, Any] = {}
    for i, step in enumerate(workflow["steps"], 1):
        check_cancelled(cancel_event)
        act = step["action"]
        if on_step:
            on_step(i, act, "running")
        try:
            if act == "click":
                gui.click(step["x"], step["y"])
            elif act == "double_click":
                gui.doubleClick(step["x"], step["y"], interval=0.13)
            elif act == "move":
                gui.moveTo(step["x"], step["y"], duration=0.2)
            elif act == "scroll":
                gui.scroll(step["delta"])
            elif act == "type_text":
                text = template(step["value"], values)
                if any(ord(ch) > 127 for ch in text):
                    raise WorkflowError("desktop type_text supports ASCII; use an OS keyboard method for Unicode")
                gui.write(text, interval=0.02)
            elif act == "press":
                key = step["key"].lower()
                if key not in SAFE_KEYS:
                    raise WorkflowError(f"desktop key not allowlisted: {key}")
                gui.press(key)
            elif act == "hotkey":
                keys = [k.lower() for k in step["keys"]]
                if any(k not in SAFE_KEYS for k in keys):
                    raise WorkflowError("desktop hotkey contains an unsupported key")
                gui.hotkey(*keys)
            elif act == "wait_ms":
                interruptible_wait(step["durationMs"], cancel_event)
            elif act == "screenshot":
                filename = step.get("filename", f"desktop-{i}.png")
                if not filename.lower().endswith(".png"):
                    filename += ".png"
                result = artifacts / filename
                gui.screenshot().save(str(result))
                outputs.setdefault("artifacts", []).append(str(result))
            elif act in {"ui_click", "ui_fill", "ui_assert_text", "ui_extract_text"}:
                from .desktop_access import execute_ui_step
                result = run_step_with_retry(step, lambda: execute_ui_step(step, values), cancel_event=cancel_event)
                if act == "ui_extract_text":
                    outputs[step["as"]] = result
            elif act == "assert_image":
                # The trusted image must reside alongside the workflow's assets;
                # arbitrary filesystem reads are deliberately unsupported.
                assets_dir = artifacts.parent.parent / "assets"
                if not step["image"].lower().endswith(".png"):
                    raise WorkflowError("reference image must be a PNG")
                reference = assets_dir / step["image"]
                if not reference.is_file() or reference.is_symlink():
                    raise WorkflowError("reference image not found under assets/")
                try:
                    match = run_step_with_retry(step, lambda: gui.locateOnScreen(str(reference), confidence=0.90), cancel_event=cancel_event)
                except (OSError, ValueError) as exc:
                    raise WorkflowError("image recognition unavailable; install opencv-python") from exc
                if match is None:
                    raise WorkflowError("reference image not visible on screen")
            else:
                raise WorkflowError(f"unsupported desktop action: {act}")
        except RunCancelled:
            if on_step:
                on_step(i, act, "cancelled")
            raise
        except Exception as exc:
            if on_step:
                on_step(i, act, "failed")
            # Never echo typed values back from the GUI engine.
            if isinstance(exc, WorkflowError):
                raise WorkflowError(f"desktop step {i}: {exc}") from None
            raise WorkflowError(f"desktop step {i} ({act}) failed: {type(exc).__name__}") from None
        if on_step:
            on_step(i, act, "passed")
    return outputs


def record_desktop(name: str, output_dir: Path, *, description: str = "Guided desktop mouse automation", smart: bool = False) -> Path:
    """Record mouse clicks/scroll, stop with F12. Never hooks or stores typed keys.

    Users add `type_text` steps with {{variable}} in the JSON editor. This is
    intentionally a pointer recorder, not a system-wide keylogger.
    """
    try:
        from pynput import keyboard, mouse
    except ImportError as exc:
        raise WorkflowError("Desktop recorder requires: pip install 'human2api[desktop]'") from exc
    from threading import Event
    from .models import save_workflow, workflow_file
    stop = Event()
    steps: list[dict[str, Any]] = []
    def click(x: float, y: float, button: Any, pressed: bool) -> None:
        if pressed and str(button).endswith("left") and not stop.is_set() and len(steps) < 250:
            result = None
            if smart:
                from .desktop_access import selector_at_point
                result = selector_at_point(int(x), int(y))
            steps.append(result or {"action": "click", "x": int(x), "y": int(y)})
    def scroll(x: float, y: float, dx: float, dy: float) -> None:
        if not stop.is_set() and len(steps) < 250 and dy:
            steps.append({"action": "scroll", "delta": int(max(-100, min(100, dy)))})
    def key_press(key: Any) -> bool | None:
        if key == keyboard.Key.f12:
            stop.set()
            return False
        return None
    print("DESKTOP RECORDING: mouse clicks and scrolling only. Press F12 to stop.")
    if smart:
        print("Windows UIA smart capture enabled. Stable non-password automation IDs replace coordinates when available.")
    print("NO keyboard text/passwords are captured. Review coordinates before sharing.")
    with mouse.Listener(on_click=click, on_scroll=scroll) as mouse_listener, keyboard.Listener(on_press=key_press):
        stop.wait()
        mouse_listener.stop()
    if not steps:
        raise WorkflowError("no desktop pointer actions recorded")
    path = workflow_file(output_dir, name)
    if path.exists():
        raise WorkflowError("workflow already exists")
    return save_workflow(path, {"schemaVersion": 1, "name": name, "description": description, "target": "desktop", "permissions": "write", "inputs": {}, "steps": steps})
