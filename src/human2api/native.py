"""Optional native accessibility adapters. No keylogging, clipboard or shell use.

Windows uses pywinauto in desktop_access. macOS uses Apple's AX API via PyObjC;
Linux uses AT-SPI via the distro's python3-pyatspi. A logged-in, explicitly
permitted accessibility session is required. These adapters never grant it.
"""
from __future__ import annotations

from collections import deque
from types import SimpleNamespace
from typing import Any

from .models import WorkflowError

LIMIT = 3000


def descendants(item: Any) -> list[Any]:
    queue = deque(item.children())
    result = []
    while queue:
        current = queue.popleft()
        result.append(current)
        if len(result) > LIMIT:
            raise WorkflowError("accessibility tree exceeds safe inspection limit")
        queue.extend(current.children())
    return result


class AtspiControl:
    def __init__(self, obj: Any, api: Any, top: Any = None):
        self.obj, self.api, self.top = obj, api, top

    @property
    def element_info(self) -> Any:
        attrs = dict(s.split(":", 1) for s in self.obj.getAttributes() if ":" in s)
        role = self.obj.getRoleName()
        return SimpleNamespace(name=self.obj.name or "", control_type=role,
            automation_id=attrs.get("id", attrs.get("accessible-id", "")),
            is_password="password" in role.lower())

    def children(self) -> list[Any]:
        n = self.obj.childCount
        if n > LIMIT:
            raise WorkflowError("accessibility tree exceeds safe inspection limit")
        values = [self.obj.getChildAtIndex(i) for i in range(n)]
        return [AtspiControl(child, self.api, self.top or self) for child in values if child is not None]

    def descendants(self) -> list[Any]:
        return descendants(self)

    def is_visible(self) -> bool:
        state = self.obj.getState()
        return state.contains(self.api.STATE_SHOWING) and state.contains(self.api.STATE_VISIBLE)

    def is_enabled(self) -> bool:
        return self.obj.getState().contains(self.api.STATE_ENABLED)

    def window_text(self) -> str:
        if self.element_info.is_password:
            raise WorkflowError("password controls cannot be read")
        try:
            text = self.obj.queryText()
            return text.getText(0, min(text.characterCount, 10000))
        except NotImplementedError:
            return self.obj.name or ""

    def set_edit_text(self, value: str) -> None:
        if self.element_info.is_password:
            raise WorkflowError("password controls cannot be selected")
        if not self.obj.queryEditableText().setTextContents(value):
            raise WorkflowError("AT-SPI rejected text input")

    def click_input(self) -> None:
        action = self.obj.queryAction()
        choices = [i for i in range(action.nActions) if action.getName(i).lower() in {"click", "press", "activate"}]
        if len(choices) != 1 or not action.doAction(choices[0]):
            raise WorkflowError("control has no unambiguous accessible click action")

    def top_level_parent(self) -> Any:
        return self.top or self


class AtspiDesktop:
    def __init__(self) -> None:
        try:
            import pyatspi
        except ImportError as exc:
            raise WorkflowError("Linux native selectors need distro python3-pyatspi and an AT-SPI desktop session") from exc
        self.api = pyatspi

    def windows(self, *, title: str | None = None) -> list[Any]:
        desk = self.api.Registry.getDesktop(0)
        result = []
        for app in desk:
            for window in app:
                control = AtspiControl(window, self.api)
                if control.is_visible() and (title is None or window.name == title):
                    result.append(control)
        return result

    def from_point(self, x: int, y: int) -> Any:
        candidates = []
        for window in self.windows():
            try:
                obj = window.obj.queryComponent().getAccessibleAtPoint(x, y, self.api.DESKTOP_COORDS)
                for _ in range(40):
                    if obj is None:
                        break
                    child = obj.queryComponent().getAccessibleAtPoint(x, y, self.api.DESKTOP_COORDS)
                    if child is None or child == obj:
                        candidates.append(AtspiControl(obj, self.api, window))
                        break
                    obj = child
            except NotImplementedError:
                continue
        if len(candidates) != 1:
            return None
        return candidates[0]


class AXControl:
    def __init__(self, obj: Any, api: Any):
        self.obj, self.api = obj, api

    def attr(self, name: str, default: Any = None) -> Any:
        error, value = self.api.AXUIElementCopyAttributeValue(self.obj, name, None)
        return value if error == 0 and value is not None else default

    @property
    def element_info(self) -> Any:
        role = self.attr("AXRole", "")
        return SimpleNamespace(name=self.attr("AXTitle", "") or self.attr("AXDescription", ""),
            automation_id=self.attr("AXIdentifier", ""), control_type=role,
            is_password=self.attr("AXSubrole", "") == "AXSecureTextField")

    def children(self) -> list[Any]:
        values = self.attr("AXChildren", [])
        if len(values) > LIMIT:
            raise WorkflowError("accessibility tree exceeds safe inspection limit")
        return [AXControl(x, self.api) for x in values]

    def descendants(self) -> list[Any]:
        return descendants(self)

    def is_visible(self) -> bool:
        return not bool(self.attr("AXHidden", False) or self.attr("AXMinimized", False))

    def is_enabled(self) -> bool:
        return bool(self.attr("AXEnabled", True))

    def window_text(self) -> str:
        if self.element_info.is_password:
            raise WorkflowError("password controls cannot be read")
        return str(self.attr("AXValue", self.attr("AXTitle", "")))[:10000]

    def set_edit_text(self, value: str) -> None:
        if self.element_info.is_password:
            raise WorkflowError("password controls cannot be selected")
        error = self.api.AXUIElementSetAttributeValue(self.obj, "AXValue", value)
        if error != 0:
            raise WorkflowError("AX control does not support text input")

    def click_input(self) -> None:
        if self.api.AXUIElementPerformAction(self.obj, "AXPress") != 0:
            raise WorkflowError("AX control does not support a press action")

    def top_level_parent(self) -> Any:
        top = self.attr("AXWindow")
        if top is None:
            raise WorkflowError("no containing accessibility window")
        return AXControl(top, self.api)


class AXDesktop:
    def __init__(self) -> None:
        try:
            import ApplicationServices
            from AppKit import NSWorkspace
        except ImportError as exc:
            raise WorkflowError("macOS native selectors require human2api[accessibility]") from exc
        self.api, self.workspace = ApplicationServices, NSWorkspace.sharedWorkspace()
        if not self.api.AXIsProcessTrusted():
            raise WorkflowError("Grant Accessibility permission to this app in macOS System Settings, then retry")

    def windows(self, *, title: str | None = None) -> list[Any]:
        result = []
        for app in self.workspace.runningApplications():
            root = AXControl(self.api.AXUIElementCreateApplication(app.processIdentifier()), self.api)
            for obj in root.attr("AXWindows", []):
                control = AXControl(obj, self.api)
                if control.is_visible() and (title is None or control.attr("AXTitle", "") == title):
                    result.append(control)
        return result

    def from_point(self, x: int, y: int) -> Any:
        root = self.api.AXUIElementCreateSystemWide()
        error, obj = self.api.AXUIElementCopyElementAtPosition(root, float(x), float(y), None)
        return AXControl(obj, self.api) if error == 0 and obj is not None else None
