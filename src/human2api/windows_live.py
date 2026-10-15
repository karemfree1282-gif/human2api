"""Real Windows UI Automation driver backed by pywinauto.

This module is deliberately imported only on Windows. It never substitutes simulated
nodes for real controls when a native desktop workflow is requested.
"""
from __future__ import annotations

import sys
from typing import Dict, List

from human2api.desktop_access import DesktopAccessibleNode


class WindowsUIABridge:
    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Windows UI Automation requires Microsoft Windows; it cannot run on this OS.")
        try:
            from pywinauto import Desktop
        except ImportError as exc:
            raise RuntimeError('Windows automation requires pywinauto. Install: py -m pip install ".[accessibility]"') from exc
        self.desktop = Desktop(backend="uia")
        self.controls: Dict[str, object] = {}
        self.windows: Dict[str, object] = {}

    @staticmethod
    def _safe_attr(obj, name: str, default=""):
        try:
            value = getattr(obj, name, default)
            return value() if callable(value) else value
        except Exception:
            return default

    def snapshot(self, allowed_apps: List[str], active_window: str = "") -> List[DesktopAccessibleNode]:
        if not allowed_apps:
            raise PermissionError("Windows UIA live automation requires an explicit allowedApps list.")
        allowed = [x.strip().casefold() for x in allowed_apps if x.strip()]
        if not allowed:
            raise PermissionError("No allowed Windows application configured.")
        self.controls.clear()
        self.windows.clear()
        result = []
        try:
            windows = self.desktop.windows(visible_only=True)
        except Exception as exc:
            raise RuntimeError(f"Unable to query Windows UI Automation windows: {exc}") from exc
        for window in windows:
            info = window.element_info
            title = str(self._safe_attr(info, "name") or self._safe_attr(window, "window_text") or "")
            if not title:
                continue
            title_cf = title.casefold()
            if not any(x in title_cf for x in allowed):
                continue
            if active_window and active_window.casefold() not in title_cf and title_cf not in active_window.casefold():
                continue
            self.windows[title] = window
            try:
                descendants = window.descendants()
            except Exception:
                continue
            for index, wrapper in enumerate(descendants[:1024]):
                elem = wrapper.element_info
                role = str(self._safe_attr(elem, "control_type") or "").lower()
                role = {"edit": "textbox", "button": "button", "check box": "checkbox", "checkbox": "checkbox", "text": "label", "combo box": "combobox", "combobox": "combobox", "list item": "listitem"}.get(role, role)
                automation_id = str(self._safe_attr(elem, "automation_id") or "")
                name = str(self._safe_attr(elem, "name") or "")
                is_password = bool(self._safe_attr(elem, "is_password", False))
                if is_password or any(x in (automation_id + " " + name).casefold() for x in ("password", "passcode", "pin code", "otp", "cvv")):
                    continue
                rectangle = self._safe_attr(elem, "rectangle", None)
                if rectangle is None:
                    continue
                try:
                    bounds = (int(rectangle.left), int(rectangle.top), int(rectangle.width()), int(rectangle.height()))
                except (TypeError, ValueError, AttributeError):
                    continue
                if bounds[2] <= 0 or bounds[3] <= 0:
                    continue
                visible = bool(self._safe_attr(elem, "visible", True))
                enabled = bool(self._safe_attr(elem, "enabled", True))
                if not visible:
                    continue
                # Node IDs are valid for this fresh snapshot only. Re-resolve each workflow step.
                node_id = f"{title}:{index}"
                value = str(self._safe_attr(wrapper, "get_value") or self._safe_attr(wrapper, "window_text") or "")
                node = DesktopAccessibleNode(
                    node_id=node_id, automation_id=automation_id, name=name, role=role,
                    window_title=title, app_name=title, bounds=bounds, enabled=enabled,
                    visible=visible, value=value,
                )
                self.controls[node_id] = wrapper
                result.append(node)
        return result

    def focus_window(self, title: str, allowed_apps: List[str]) -> str:
        # Resolve only among visible windows and the explicit allowlist.
        self.snapshot(allowed_apps)
        matches = [(k, v) for k, v in self.windows.items() if title.casefold() in k.casefold()]
        if len(matches) != 1:
            raise RuntimeError(f"Expected exactly one allowed Windows window matching {title!r}; found {len(matches)}.")
        name, window = matches[0]
        window.set_focus()
        return name

    def resize_window(self, title: str, width: int, height: int) -> None:
        if width < 100 or height < 100 or width > 10000 or height > 10000:
            raise ValueError("Requested Windows window size is invalid.")
        window = self.windows.get(title)
        if window is None:
            raise RuntimeError("Windows target window is no longer available.")
        window.move_window(width=width, height=height, repaint=True)

    def action(self, node: DesktopAccessibleNode, action: str, text: str | None = None):
        wrapper = self.controls.get(node.node_id)
        if wrapper is None:
            raise RuntimeError("Windows UIA element disappeared before execution; retry by refreshing the workflow.")
        if action in ("type", "type_text", "fill", "select"):
            if node.role not in ("textbox", "combobox", "edit"):
                raise RuntimeError("Refusing to enter text into an unexpected Windows control type.")
            wrapper.set_edit_text(str(text or ""))
            return str(text or "")
        if action in ("click", "double_click"):
            if node.role not in ("button", "checkbox", "radio", "tab", "menuitem", "listitem", "link"):
                raise RuntimeError("Refusing to click an unexpected Windows control type.")
            if action == "double_click":
                wrapper.double_click_input()
            else:
                # InvokePattern is accessibility-native and avoids screen coordinates.
                try:
                    wrapper.invoke()
                except (AttributeError, NotImplementedError):
                    wrapper.click_input()
            return "invoked"
        if action == "extract_text":
            return str(self._safe_attr(wrapper, "get_value") or self._safe_attr(wrapper, "window_text") or node.name)
        raise ValueError(f"Unsupported live Windows UIA action: {action}")
