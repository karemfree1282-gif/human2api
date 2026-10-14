"""Desktop Accessibility (Windows UIA, macOS AX, Live Linux GTK3/ATK/X11) and Android Companion Test Suite."""

from __future__ import annotations

import time
import unittest

from human2api.android import (
    AndroidCompanionClient,
    AndroidNode,
    AndroidSessionExpiredError,
    AndroidUnauthorizedPackageError,
)
from human2api.desktop import (
    LinuxATSPIAdapter,
    MacOSAXAdapter,
    WindowsUIAAdapter,
)
from human2api.desktop_access import DesktopAccessibleNode, detect_linux_display_protocol
from human2api.execution import CancellationToken
from human2api.models import AssertionSpec, InputSpec, Workflow, WorkflowStep
from human2api.native import LiveGTKAtkApplicationHarness
from human2api.runner import WorkflowRunner


class TestDesktopAndAndroidEngines(unittest.TestCase):
    def test_live_linux_gtk3_atk_x11_workflow(self) -> None:
        """Real OS-level test on Linux using GTK 3.0 + ATK Accessibility + Xvnc X11 display (NOT a mock!)."""
        harness = LiveGTKAtkApplicationHarness()
        started = harness.start()
        self.assertTrue(started, "GTK3 + ATK + Xvnc should start cleanly on this Linux machine.")
        try:
            adapter = harness.build_live_adapter()
            wf = Workflow(
                name="Live GTK3 Arabic & English Form",
                target="linux-atspi",
                mode="write",
                allowedApps=[harness.app_name],
                inputs={
                    "customer": InputSpec(type="string", default="شركة النيل للبرمجيات - Nile Soft"),
                    "notes": InputSpec(type="string", default="اعتماد رقم #774"),
                },
                steps=[
                    WorkflowStep(
                        action="type",
                        selector='automationId="customer_entry"',
                        automationId="customer_entry",
                        role="textbox",
                        text="${input:customer}",
                        isWriteAction=True,
                    ),
                    WorkflowStep(
                        action="type",
                        selector='automationId="notes_entry"',
                        automationId="notes_entry",
                        role="textbox",
                        text="${input:notes}",
                        isWriteAction=True,
                    ),
                    WorkflowStep(
                        action="click",
                        selector='automationId="save_button"',
                        automationId="save_button",
                        role="button",
                        isWriteAction=True,
                        idempotent=False,
                    ),
                ],
                assertions=[
                    AssertionSpec(
                        type="assert_value",
                        selector='automationId="status_label"',
                        expected="تم الحفظ: شركة النيل للبرمجيات - Nile Soft | اعتماد رقم #774",
                        match="exact",
                    )
                ],
            )
            runner = WorkflowRunner(desktop_adapter=adapter)
            rep = runner.run(wf, allow_write=True)
            self.assertEqual(rep.status, "passed", msg=f"Live GTK/ATK run failed: {rep.error}")
            # Verify the real native GTK widget text was updated
            actual_gtk_label = harness.widgets["status_label"].get_text()
            self.assertEqual(actual_gtk_label, "تم الحفظ: شركة النيل للبرمجيات - Nile Soft | اعتماد رقم #774")
        finally:
            harness.stop()

    def test_windows_uia_arabic_unicode_resize_and_multiwindow(self) -> None:
        """Verify Windows UIA adapter handles AutomationId, Arabic/English text, multi-window focus, and window resizing."""
        nodes = [
            DesktopAccessibleNode(
                node_id="win1_edit",
                automation_id="txtArabicNote",
                name="حقل النص العربي",
                role="textbox",
                window_title="المفكرة - Notepad",
                app_name="Notepad",
                bounds=(20, 40, 400, 120),
            ),
            DesktopAccessibleNode(
                node_id="win1_btn",
                automation_id="btnSave",
                name="حفظ Save",
                role="button",
                window_title="المفكرة - Notepad",
                app_name="Notepad",
                bounds=(50, 200, 100, 36),
            ),
            DesktopAccessibleNode(
                node_id="win2_status",
                automation_id="lblConfirm",
                name="تم الحفظ بنجاح",
                role="label",
                window_title="نافذة التأكيد",
                app_name="Notepad",
                bounds=(30, 30, 240, 32),
                value="مكتمل",
            ),
        ]
        adapter = WindowsUIAAdapter(nodes)
        wf = Workflow(
            name="Windows UIA Multi-Window & Resize",
            target="windows-uia",
            mode="write",
            allowedApps=["Notepad"],
            steps=[
                WorkflowStep(action="focus_window", windowTitle="المفكرة - Notepad"),
                WorkflowStep(action="resize_window", windowTitle="المفكرة - Notepad", x=1600, y=900),
                WorkflowStep(
                    action="type",
                    selector='automationId="txtArabicNote"',
                    text="بسم الله — تجربة إدخال عربي وإنجليزي 123",
                    role="textbox",
                    isWriteAction=True,
                ),
                WorkflowStep(
                    action="click",
                    selector='automationId="btnSave"',
                    role="button",
                    isWriteAction=True,
                ),
                WorkflowStep(action="focus_window", windowTitle="نافذة التأكيد"),
                WorkflowStep(
                    action="assert_value",
                    selector='automationId="lblConfirm"',
                    expected="مكتمل",
                    match="exact",
                ),
            ],
        )
        runner = WorkflowRunner(desktop_adapter=adapter)
        rep = runner.run(wf, allow_write=True)
        self.assertEqual(rep.status, "passed", msg=rep.error)
        self.assertEqual(adapter.nodes["win1_edit"].value, "بسم الله — تجربة إدخال عربي وإنجليزي 123")
        # Bounds scaled after resize_window
        self.assertGreater(adapter.nodes["win1_edit"].bounds[2], 400)

    def test_macos_ax_permission_check_and_unauthorized_app_block(self) -> None:
        node = DesktopAccessibleNode(
            node_id="ax_btn",
            automation_id="AXConfirmBtn",
            name="Confirm",
            role="button",
            window_title="TextEdit",
            app_name="TextEdit",
        )
        adapter = MacOSAXAdapter([node], enforce_os_trust=False)
        wf_blocked = Workflow(
            name="macOS Unauthorized App Test",
            target="macos-ax",
            mode="write",
            allowedApps=["Safari"],  # TextEdit is NOT allowed
            steps=[WorkflowStep(action="click", selector='automationId="AXConfirmBtn"', role="button", isWriteAction=True)],
        )
        runner = WorkflowRunner(desktop_adapter=adapter)
        rep = runner.run(wf_blocked, allow_write=True)
        self.assertEqual(rep.status, "failed")
        self.assertIn("not in allowedApps", rep.error or "")

    def test_android_companion_consent_package_scope_unicode_and_stop(self) -> None:
        nodes = [
            AndroidNode(
                node_id="a1",
                resource_id="com.example.shop:id/search_input",
                text="",
                content_desc="بحث المنتجات",
                class_name="android.widget.EditText",
                package_name="com.example.shop",
                editable=True,
            ),
            AndroidNode(
                node_id="a2",
                resource_id="com.example.shop:id/password_input",
                text="SecretPin123",
                content_desc="كلمة المرور",
                class_name="android.widget.EditText",
                package_name="com.example.shop",
                editable=True,
                is_password=True,
            ),
            AndroidNode(
                node_id="a3",
                resource_id="com.example.shop:id/submit_btn",
                text="تأكيد الطلب",
                content_desc="تأكيد الطلب",
                class_name="android.widget.Button",
                package_name="com.example.shop",
                clickable=True,
            ),
        ]
        client = AndroidCompanionClient(nodes=nodes, consent_granted=True, allowed_packages=["com.example.shop"])

        # 1. Verify password event recording is sanitized
        ev = client.record_accessibility_event(
            {"packageName": "com.example.shop", "resourceId": "com.example.shop:id/password_input", "isPassword": True, "text": "MyPin99"}
        )
        self.assertIsNone(ev["text"])
        self.assertTrue(ev["is_password"])

        # 2. Verify unauthorized package event is rejected
        with self.assertRaises(AndroidUnauthorizedPackageError):
            client.record_accessibility_event({"packageName": "com.android.bank", "resourceId": "id/btn"})

        # 3. Execute valid Arabic/Unicode workflow on authorized package
        wf = Workflow(
            name="Android Arabic Order",
            target="android-companion",
            mode="write",
            allowedPackages=["com.example.shop"],
            steps=[
                WorkflowStep(
                    action="type_text",
                    packageName="com.example.shop",
                    resourceId="com.example.shop:id/search_input",
                    role="textbox",
                    text="هاتف ذكي 5G — الفئة الممتازة",
                    isWriteAction=True,
                ),
                WorkflowStep(
                    action="click",
                    packageName="com.example.shop",
                    resourceId="com.example.shop:id/submit_btn",
                    role="button",
                    isWriteAction=True,
                ),
                WorkflowStep(
                    action="assert_text",
                    packageName="com.example.shop",
                    selector="com.example.shop:id/search_input",
                    expected="هاتف ذكي 5G",
                    match="contains",
                ),
            ],
        )
        runner = WorkflowRunner(android_adapter=client)
        rep = runner.run(wf, allow_write=True)
        self.assertEqual(rep.status, "passed", msg=rep.error)

        # 4. Verify session expiration blocks execution
        client.grant_user_consent(["com.example.shop"], ttl_seconds=0.01)
        time.sleep(0.03)
        rep_expired = runner.run(wf, allow_write=True)
        self.assertEqual(rep_expired.status, "failed")
        self.assertIn("expired", rep_expired.error or "")

        # 5. Verify immediate STOP button cancels execution
        client.grant_user_consent(["com.example.shop"], ttl_seconds=300)
        client.trigger_stop()
        rep_stopped = runner.run(wf, allow_write=True)
        self.assertEqual(rep_stopped.status, "cancelled")


if __name__ == "__main__":
    unittest.main()
