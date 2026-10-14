"""Native Linux GTK3 + ATK + X11 (Xvnc/xdotool) Live Accessibility Harness & Native Packaging Helpers."""

from __future__ import annotations

import os
import subprocess
import time
from typing import Any, Dict, Optional

from human2api.desktop import LinuxATSPIAdapter
from human2api.desktop_access import DesktopAccessibleNode, detect_linux_display_protocol


class LiveGTKAtkApplicationHarness:
    """Spawns a real GTK 3.0 widget tree backed by ATK Accessibility objects (and Xvnc on Linux)
    so Linux desktop workflows can be recorded and executed against real native GTK/ATK widgets,
    not merely Python mocks.
    """

    def __init__(self, app_name: str = "Human2API-GTK-Demo", window_title: str = "محرر المهام - Task Editor") -> None:
        self.app_name = app_name
        self.window_title = window_title
        self.xvnc_proc: Optional[subprocess.Popen] = None
        self.display = ":99"
        self.widgets: Dict[str, Any] = {}
        self.window = None

    def start(self) -> bool:
        caps = detect_linux_display_protocol()
        if not caps.get("gtk_atk_available"):
            return False

        if not os.environ.get("DISPLAY") and caps.get("xvnc_available"):
            self.xvnc_proc = subprocess.Popen(
                ["Xvnc", self.display, "-SecurityTypes", "None", "-geometry", "1024x768", "-depth", "24"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(0.8)
            os.environ["DISPLAY"] = self.display

        import gi

        gi.require_version("Gdk", "3.0")
        gi.require_version("Gtk", "3.0")
        gi.require_version("Atk", "1.0")
        from gi.repository import Atk, Gdk, Gtk  # noqa: F401

        Gdk.Display.open(os.environ.get("DISPLAY", self.display))
        Gtk.init([])

        win = Gtk.Window(title=self.window_title)
        win.set_default_size(640, 480)
        win_atk = win.get_accessible()
        win_atk.set_name(self.window_title)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        win.add(box)

        entry_customer = Gtk.Entry()
        entry_customer.set_name("customer_entry")
        atk_cust = entry_customer.get_accessible()
        atk_cust.set_name("اسم العميل - Customer Name")
        atk_cust.set_description("customer_entry")
        box.pack_start(entry_customer, False, False, 0)

        entry_notes = Gtk.Entry()
        entry_notes.set_name("notes_entry")
        atk_notes = entry_notes.get_accessible()
        atk_notes.set_name("ملاحظات الفاتورة - Invoice Notes")
        atk_notes.set_description("notes_entry")
        box.pack_start(entry_notes, False, False, 0)

        status_label = Gtk.Label(label="جاهز - Ready")
        status_label.set_name("status_label")
        atk_status = status_label.get_accessible()
        atk_status.set_name("حالة العملية - Status")
        atk_status.set_description("status_label")
        box.pack_start(status_label, False, False, 0)

        btn_save = Gtk.Button(label="حفظ المهمة - Save Task")
        btn_save.set_name("save_button")
        atk_btn = btn_save.get_accessible()
        atk_btn.set_name("حفظ المهمة - Save Task")
        atk_btn.set_description("save_button")

        def _on_save_clicked(_btn):
            cust_val = entry_customer.get_text()
            notes_val = entry_notes.get_text()
            status_label.set_text(f"تم الحفظ: {cust_val} | {notes_val}")

        btn_save.connect("clicked", _on_save_clicked)
        box.pack_start(btn_save, False, False, 0)

        win.show_all()
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)

        self.window = win
        self.widgets = {
            "customer_entry": entry_customer,
            "notes_entry": entry_notes,
            "save_button": btn_save,
            "status_label": status_label,
        }
        return True

    def build_live_adapter(self) -> LinuxATSPIAdapter:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Atk, Gtk

        harness = self

        class LiveGTKAdapter(LinuxATSPIAdapter):
            def sync_from_gtk(self_inner) -> None:
                while Gtk.events_pending():
                    Gtk.main_iteration_do(False)
                self_inner.nodes.clear()
                for key, widget in harness.widgets.items():
                    atk_obj = widget.get_accessible()
                    role_name = Atk.role_get_name(atk_obj.get_role()) or "widget"
                    if "entry" in key or "text" in role_name:
                        norm_role = "textbox"
                        val = widget.get_text() if hasattr(widget, "get_text") else ""
                    elif "button" in key or "push button" in role_name:
                        norm_role = "button"
                        val = widget.get_label() if hasattr(widget, "get_label") else ""
                    else:
                        norm_role = "label"
                        val = widget.get_text() if hasattr(widget, "get_text") else ""
                    alloc = widget.get_allocation()
                    bounds = (
                        max(0, alloc.x),
                        max(0, alloc.y),
                        max(24, alloc.width),
                        max(16, alloc.height),
                    )
                    self_inner.register_node(
                        DesktopAccessibleNode(
                            node_id=key,
                            automation_id=key,
                            name=atk_obj.get_name() or key,
                            role=norm_role,
                            window_title=harness.window_title,
                            app_name=harness.app_name,
                            bounds=bounds,
                            visible=widget.get_visible(),
                            enabled=widget.get_sensitive(),
                            value=val,
                        )
                    )

            def snapshot_candidates(self_inner):
                self_inner.sync_from_gtk()
                return super().snapshot_candidates()

            def match_primary(self_inner, selector: str):
                self_inner.sync_from_gtk()
                return super().match_primary(selector)

            def perform_node_action(self_inner, node: DesktopAccessibleNode, action: str, text_val: Optional[str] = None):
                widget = harness.widgets[node.node_id]
                if action in ("type", "type_text", "fill") and hasattr(widget, "set_text"):
                    widget.set_text(str(text_val or ""))
                elif action in ("click", "double_click") and hasattr(widget, "clicked"):
                    widget.clicked()
                while Gtk.events_pending():
                    Gtk.main_iteration_do(False)
                self_inner.sync_from_gtk()
                return self_inner.nodes[node.node_id].value

        adapter = LiveGTKAdapter()
        adapter.sync_from_gtk()
        return adapter

    def stop(self) -> None:
        if self.window is not None:
            try:
                self.window.destroy()
            except Exception:
                pass
            self.window = None
        if self.xvnc_proc is not None:
            try:
                self.xvnc_proc.terminate()
                self.xvnc_proc.wait(timeout=2)
            except Exception:
                pass
            self.xvnc_proc = None
