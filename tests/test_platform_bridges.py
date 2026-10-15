"""Host-side platform transport regression tests, no phone or Windows machine required.

These verify real HTTP commands and Windows UIA driver dispatch using a fake *transport*.
They do NOT claim to replace real-device end-to-end tests.
"""
from __future__ import annotations

import json
import sys
import threading
import types
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from human2api.android import LiveAndroidCompanionClient
from human2api.desktop_access import DesktopAccessibleNode
from human2api.execution import CancellationToken
from human2api.models import Workflow, WorkflowStep, AssertionSpec
from human2api.runner import WorkflowRunner


class PhoneEmulatorHandler(BaseHTTPRequestHandler):
    token = "temporary-pair-token"
    last_action = None
    text = ""

    def log_message(self, *_):
        pass

    def respond(self, code, data):
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/health":
            return self.respond(200, {"status": "ok"})
        if self.headers.get("X-H2A-Token") != self.token:
            return self.respond(403, {"error": "pairing token required"})
        if self.path == "/nodes":
            return self.respond(200, {"status": "ok", "package_name": "com.example.demo", "nodes": [
                {"node_id": "0.0", "resource_id": "com.example.demo:id/input", "text": self.text,
                 "content_desc": "Customer", "class_name": "android.widget.EditText", "package_name": "com.example.demo",
                 "clickable": True, "editable": True, "enabled": True, "visible": True, "scrollable": False},
                {"node_id": "0.1", "resource_id": "com.example.demo:id/submit", "text": "Submit",
                 "content_desc": "Submit", "class_name": "android.widget.Button", "package_name": "com.example.demo",
                 "clickable": True, "editable": False, "enabled": True, "visible": True, "scrollable": False},
            ]})
        self.respond(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        data = json.loads(self.rfile.read(length))
        if self.path == "/stop":
            return self.respond(200, {"status": "stopped"})
        if self.headers.get("X-H2A-Token") != self.token:
            return self.respond(403, {"error": "pairing token required"})
        if self.path != "/action":
            return self.respond(404, {"error": "not found"})
        self.__class__.last_action = data
        if data.get("node_id") == "0.0" and data.get("action") in ("type_text", "type", "fill"):
            self.__class__.text = data["text"]
        self.respond(200, {"status": "ok", "performed": True})


class TestRealAndroidProtocol(unittest.TestCase):
    def setUp(self):
        PhoneEmulatorHandler.text = ""
        PhoneEmulatorHandler.last_action = None
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), PhoneEmulatorHandler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_real_http_text_click_and_post_assertion(self):
        wf = Workflow(name="Android live protocol", target="android-companion", mode="write",
                      allowedPackages=["com.example.demo"], steps=[
            WorkflowStep(action="type_text", selector="com.example.demo:id/input", text="مرحباً بالعالم", packageName="com.example.demo", isWriteAction=True),
            WorkflowStep(action="click", selector="com.example.demo:id/submit", packageName="com.example.demo", isWriteAction=True),
        ], assertions=[AssertionSpec(type="assert_text", selector="com.example.demo:id/input", expected="مرحباً بالعالم", match="exact")])
        client = LiveAndroidCompanionClient(token=PhoneEmulatorHandler.token, port=self.port)
        result = WorkflowRunner(android_adapter=client).run(wf, allow_write=True)
        self.assertEqual("passed", result.status, result.error)
        self.assertEqual("مرحباً بالعالم", PhoneEmulatorHandler.text)
        self.assertEqual("click", PhoneEmulatorHandler.last_action["action"])
        self.assertEqual(1, result.assertions_passed)

    def test_bad_pairing_token_fails_closed(self):
        wf = Workflow(name="Reject token", target="android-companion", mode="write",
                      allowedPackages=["com.example.demo"], steps=[
            WorkflowStep(action="click", selector="com.example.demo:id/submit", packageName="com.example.demo", isWriteAction=True)
        ])
        result = WorkflowRunner(android_adapter=LiveAndroidCompanionClient(token="bad", port=self.port)).run(wf, allow_write=True)
        self.assertEqual("failed", result.status)
        self.assertIn("403", result.error)

    def test_block_other_packages_before_remote_action(self):
        wf = Workflow(name="Disallowed package", target="android-companion", mode="write",
                      allowedPackages=["com.example.demo"], steps=[
            WorkflowStep(action="click", selector="com.example.demo:id/submit", packageName="com.example.untrusted", isWriteAction=True)
        ])
        result = WorkflowRunner(android_adapter=LiveAndroidCompanionClient(token=PhoneEmulatorHandler.token, port=self.port)).run(wf, allow_write=True)
        self.assertEqual("failed", result.status)
        self.assertIsNone(PhoneEmulatorHandler.last_action)

    def test_no_fake_android_success_without_phone(self):
        wf = Workflow(name="No device", target="android-companion", mode="read", steps=[WorkflowStep(action="back")])
        with patch.dict("os.environ", {"H2A_ANDROID_TOKEN": ""}):
            result = WorkflowRunner().run(wf)
        self.assertEqual("failed", result.status)
        self.assertIn("pairing", result.error.lower())


class FakeRect:
    left = 4
    top = 9
    def width(self): return 200
    def height(self): return 30


class FakeControl:
    def __init__(self, role="Edit", auto_id="editNote", name="Note", password=False):
        self.value = ""
        self.element_info = types.SimpleNamespace(
            control_type=role, automation_id=auto_id, name=name,
            is_password=password, rectangle=FakeRect(), enabled=True, visible=True,
        )
        self.invoked = False

    def set_edit_text(self, value): self.value = value
    def get_value(self): return self.value
    def window_text(self): return self.value
    def invoke(self): self.invoked = True


class FakeWindow:
    def __init__(self, controls):
        self.element_info = types.SimpleNamespace(name="Untitled - Notepad")
        self._controls = controls
        self.focused = False

    def descendants(self): return self._controls
    def set_focus(self): self.focused = True
    def move_window(self, **kw): pass


class TestWindowsUIABridge(unittest.TestCase):
    def test_native_backend_dispatch_and_allowlist(self):
        from human2api.windows_live import WindowsUIABridge
        edit = FakeControl()
        button = FakeControl("Button", "save", "Save")
        secret = FakeControl("Edit", "login_password", "Secret", True)
        window = FakeWindow([edit, button, secret])
        mock_module = types.ModuleType("pywinauto")
        mock_module.Desktop = lambda backend: types.SimpleNamespace(windows=lambda visible_only: [window])
        with patch.object(sys, "platform", "win32"), patch.dict(sys.modules, {"pywinauto": mock_module}):
            bridge = WindowsUIABridge()
        self.assertEqual([], bridge.snapshot(["Calculator"]))
        found = bridge.snapshot(["Notepad"])
        self.assertEqual(2, len(found))
        self.assertEqual("Untitled - Notepad", bridge.focus_window("Notepad", ["Notepad"]))
        self.assertEqual("نص عربي", bridge.action(found[0], "type", "نص عربي"))
        self.assertEqual("نص عربي", edit.value)
        bridge.action(found[1], "click")
        self.assertTrue(button.invoked)
        self.assertNotIn("login_password", str(found))

    def test_windows_runner_with_live_ui_accessibility_controls(self):
        from human2api.desktop import WindowsUIAAdapter
        edit = FakeControl()
        button = FakeControl("Button", "save", "Save")
        result = FakeControl("Text", "demo_result", "Result")
        def invoke():
            result.value = "Saved: " + edit.value
            button.invoked = True
        button.invoke = invoke
        window = FakeWindow([edit, button, result])
        lib = types.ModuleType("pywinauto")
        lib.Desktop = lambda backend: types.SimpleNamespace(windows=lambda visible_only: [window])
        with patch.object(sys, "platform", "win32"), patch.dict(sys.modules, {"pywinauto": lib}):
            adapter = WindowsUIAAdapter()
        wf = Workflow(name="Windows runtime bridge", target="windows-uia", mode="write",
            allowedApps=["Notepad"], steps=[
                WorkflowStep(action="focus_window", windowTitle="Notepad"),
                WorkflowStep(action="type", selector='automationId="editNote"', text="مرحبا", isWriteAction=True),
                WorkflowStep(action="click", selector='automationId="save"', isWriteAction=True),
            ], assertions=[AssertionSpec(type="assert_text", selector='automationId="demo_result"', expected="مرحبا", match="contains")])
        report = WorkflowRunner(desktop_adapter=adapter).run(wf, allow_write=True)
        self.assertEqual("passed", report.status, report.error)
        self.assertTrue(button.invoked)
        self.assertEqual("مرحبا", edit.value)
        self.assertEqual(1, report.assertions_passed)

    def test_no_windows_is_not_silently_simulated(self):
        from human2api.windows_live import WindowsUIABridge
        if sys.platform != "win32":
            with self.assertRaisesRegex(RuntimeError, "Microsoft Windows"):
                WindowsUIABridge()


if __name__ == "__main__":
    unittest.main()
