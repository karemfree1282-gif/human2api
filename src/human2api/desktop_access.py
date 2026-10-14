"""Cross-platform Desktop Accessibility Tree abstractions for Windows UIA, macOS AX, and Linux AT-SPI / ATK."""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from human2api.healing import UIElementCandidate


@dataclass
class DesktopAccessibleNode:
    node_id: str
    automation_id: str
    name: str
    role: str
    window_title: str
    app_name: str
    bounds: Tuple[int, int, int, int] = (0, 0, 100, 32)  # (x, y, width, height)
    visible: bool = True
    enabled: bool = True
    focused: bool = False
    is_password: bool = False
    value: str = ""
    children: List["DesktopAccessibleNode"] = field(default_factory=list)

    @property
    def center(self) -> Tuple[int, int]:
        x, y, w, h = self.bounds
        return (x + max(1, w) // 2, y + max(1, h) // 2)

    def to_candidate(self) -> UIElementCandidate:
        selector = (
            f'automationId="{self.automation_id}"'
            if self.automation_id
            else f'role={self.role}[name="{self.name}"]'
        )
        return UIElementCandidate(
            candidate_id=self.node_id,
            selector=selector,
            role=self.role.lower(),
            name=self.name,
            automation_id=self.automation_id,
            placeholder="",
            tag_name=self.role.lower(),
            visible=self.visible and self.bounds[2] > 0 and self.bounds[3] > 0,
            enabled=self.enabled,
            is_password=self.is_password,
            host_or_package=self.app_name or self.window_title,
            context_landmark=self.window_title,
        )


def detect_linux_display_protocol() -> Dict[str, Any]:
    """Inspect current Linux session protocol (X11 vs Wayland) and accessibility bus availability without prematurely initializing GTK display."""
    wayland_display = os.environ.get("WAYLAND_DISPLAY", "")
    x11_display = os.environ.get("DISPLAY", "")
    xdg_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
    is_wayland = bool(wayland_display or xdg_type == "wayland")
    is_x11 = bool(x11_display or xdg_type == "x11")

    gtk_available = False
    atk_available = False
    try:
        import gi

        gi.require_version("Atk", "1.0")
        gi.require_version("GIRepository", "2.0")
        from gi.repository import Atk, GIRepository  # noqa: F401

        repo = GIRepository.Repository.get_default()
        gtk_versions = repo.enumerate_versions("Gtk")
        gtk_available = "3.0" in gtk_versions
        atk_available = True
    except Exception:
        pass

    return {
        "platform": sys_platform_name(),
        "is_wayland": is_wayland,
        "is_x11": is_x11,
        "display": x11_display or wayland_display,
        "wayland_global_coordinate_restriction": is_wayland,
        "gtk_atk_available": gtk_available and atk_available,
        "xdotool_available": _which("xdotool") is not None,
        "xvnc_available": _which("Xvnc") is not None,
    }


def check_macos_ax_permission() -> Tuple[bool, str]:
    """Verify official macOS Accessibility permission (AXIsProcessTrusted) without attempting any bypass."""
    if platform.system().lower() != "darwin":
        return False, "Not running on macOS (Darwin)."
    try:
        import ApplicationServices  # type: ignore

        trusted = bool(ApplicationServices.AXIsProcessTrusted())
        if not trusted:
            return (
                False,
                "macOS Accessibility permission not granted. Enable this application in System Settings > Privacy & Security > Accessibility.",
            )
        return True, "macOS AXIsProcessTrusted verified."
    except Exception as exc:
        return False, f"macOS ApplicationServices unavailable: {exc}"


def sys_platform_name() -> str:
    sys_name = platform.system().lower()
    if sys_name.startswith("win"):
        return "windows-uia"
    if sys_name == "darwin":
        return "macos-ax"
    return "linux-atspi"


def _which(cmd: str) -> Optional[str]:
    for p in os.environ.get("PATH", "").split(os.pathsep):
        cand = os.path.join(p, cmd)
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None
