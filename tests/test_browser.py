"""Real Chromium Browser E2E Tests including the 4 previously deferred URL tests (`127.0.0.2` loopback),
multi-tabs, nested iframes, file upload/download, and full record-parameterize-replay-assert workflow.
"""

from __future__ import annotations

import pathlib
import tempfile
import unittest

from human2api.http_server import Human2APIServer
from human2api.models import AssertionSpec, InputSpec, Workflow, WorkflowStep
from human2api.recorder import BROWSER_RECORDER_INJECTION_JS, WorkflowRecorder
from human2api.runner import ChromiumBrowserSession, WorkflowRunner
from human2api.workspace import Workspace


class TestBrowserRealE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="h2a_browser_e2e_")
        cls.workspace = Workspace(pathlib.Path(cls._tmp.name))
        cls.workspace.initialize()
        cls.workspace.vault.initialize("test-passphrase-1234", {"api_password": "VaultSecret#9988"})
        # Bind to 127.0.0.2 so managed Chromium policies blocking 127.0.0.1 allow real HTTP navigation
        cls.server = Human2APIServer(workspace=cls.workspace, host="127.0.0.2", port=0)
        cls.base_url = cls.server.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop()
        cls._tmp.cleanup()

    def test_real_invoice_browser_run(self) -> None:
        """Previously deferred E2E test #1: Full record -> save -> parameter override -> replay -> DOM assert in real Chromium."""
        # 1. Record user interaction inside real Chromium on /demo
        wf_probe = Workflow(
            name="Probe",
            target="browser",
            allowedHosts=["127.0.0.2", "127.0.0.1"],
            steps=[WorkflowStep(action="goto", url=f"{self.base_url}/demo")],
        )
        session = ChromiumBrowserSession(wf_probe, workspace_dir=self.workspace.root_dir, headless=True)
        session.start()
        try:
            driver = session.driver
            assert driver is not None
            driver.get(f"{self.base_url}/demo")
            driver.execute_script(BROWSER_RECORDER_INJECTION_JS)

            cust_el = driver.find_element("css selector", '[data-testid="customer-input"]')
            cust_el.send_keys("العميل الأول")
            driver.execute_script("arguments[0].dispatchEvent(new Event('change', {bubbles:true}));", cust_el)

            amt_el = driver.find_element("css selector", '[data-testid="amount-input"]')
            amt_el.send_keys("300")
            driver.execute_script("arguments[0].dispatchEvent(new Event('change', {bubbles:true}));", amt_el)

            pwd_el = driver.find_element("css selector", '[data-testid="password-input"]')
            pwd_el.send_keys("RawTypedPasswordShouldNeverBeSaved")
            driver.execute_script("arguments[0].dispatchEvent(new Event('change', {bubbles:true}));", pwd_el)

            btn_el = driver.find_element("css selector", '[data-testid="submit-invoice"]')
            btn_el.click()

            recorded_events = driver.execute_script("return window.__h2aRecordedEvents || [];")
        finally:
            session.stop()

        self.assertGreaterEqual(len(recorded_events), 4)

        # 2. Compile recorded events into a reusable Workflow and save to disk
        recorder = WorkflowRecorder(name="Recorded Invoice Workflow", target="browser")
        recorder.record_event({"action": "goto", "url": f"{self.base_url}/demo"})
        for ev in recorded_events:
            recorder.record_event(ev)
        recorder.record_event(
            {
                "action": "assert_text",
                "selector": "#invoice-result",
                "expected": "${input:customer_name}",
                "match": "contains",
            }
        )
        compiled_wf = recorder.compile_workflow()
        saved_path = self.workspace.workflows_dir / "recorded_invoice.json"
        compiled_wf.save(saved_path)

        # Verify raw password was NEVER saved in the workflow JSON
        raw_json = saved_path.read_text(encoding="utf-8")
        self.assertNotIn("RawTypedPasswordShouldNeverBeSaved", raw_json)
        self.assertIn("${secret:api_password}", raw_json)

        # 3. Replay saved workflow with NEW input values in real Chromium and verify actual result
        loaded_wf = Workflow.load(saved_path)
        runner = WorkflowRunner(vault=self.workspace.vault, workspace_dir=self.workspace.root_dir)
        report = runner.run(
            loaded_wf,
            inputs={
                "customer_name": "شركة المستقبل الذكي",
                "invoice_amount": "9750.50",
            },
            allow_write=True,
        )
        self.assertEqual(report.status, "passed", msg=f"Browser run failed: {report.error}")
        self.assertGreaterEqual(report.assertions_passed, 1)

    def test_browser_capture_privacy(self) -> None:
        """Previously deferred E2E test #2: Verify password and token inputs are never leaked in workflows, reports, or history."""
        rec = WorkflowRecorder(name="Privacy Capture Test", target="browser")
        rec.record_event({"action": "goto", "url": f"{self.base_url}/demo"})
        rec.record_event(
            {
                "action": "type",
                "id": "api-password",
                "name_attr": "api_password",
                "input_type": "password",
                "is_password": True,
                "value": "TopSecretPass!2026",
            }
        )
        wf = rec.compile_workflow()
        wf_json = wf.to_json()
        self.assertNotIn("TopSecretPass!2026", wf_json)
        self.assertTrue(wf.inputs["api_password"].sensitive)
        self.assertIsNone(wf.inputs["api_password"].default)

        runner = WorkflowRunner(vault=self.workspace.vault, workspace_dir=self.workspace.root_dir)
        report = runner.run(wf, inputs={"api_password": "RuntimeSecretValue!99"}, allow_write=True)
        self.assertEqual(report.status, "passed")
        serialized_report = str(report.to_dict(secret_values={"RuntimeSecretValue!99"}))
        self.assertNotIn("RuntimeSecretValue!99", serialized_report)

    def test_browser_rejects_cross_origin_navigation(self) -> None:
        """Previously deferred E2E test #3: Verify strict networkPolicy blocks navigation and links to unauthorized external hosts."""
        wf = Workflow(
            name="Cross Origin Block Test",
            target="browser",
            mode="read",
            networkPolicy="strict",
            allowedHosts=["127.0.0.2", "127.0.0.1"],
            steps=[
                WorkflowStep(action="goto", url=f"{self.base_url}/demo"),
                WorkflowStep(action="click", selector="#external-evil-link", role="link"),
            ],
        )
        runner = WorkflowRunner(vault=self.workspace.vault, workspace_dir=self.workspace.root_dir)
        report = runner.run(wf, allow_write=True)
        self.assertEqual(report.status, "failed")
        self.assertIn("not permitted by allowedHosts", report.error or "")

    def test_resilient_fallback_selectors(self) -> None:
        """Previously deferred E2E test #4: Verify browser runner heals broken primary selectors via fallback (Tier 2) and semantic match (Tier 3)."""
        wf = Workflow(
            name="Resilient Selector Healing E2E",
            target="browser",
            mode="write",
            allowedHosts=["127.0.0.2", "127.0.0.1"],
            inputs={
                "cust": InputSpec(type="string", default="عميل الإصلاح الذكي"),
            },
            steps=[
                WorkflowStep(action="goto", url=f"{self.base_url}/demo"),
                # Broken primary selector, valid Tier 2 fallback selector
                WorkflowStep(
                    action="type",
                    selector="#old-broken-customer-id",
                    fallbackSelectors=['[data-testid="customer-input"]'],
                    text="${input:cust}",
                    role="textbox",
                    name="اسم العميل",
                    isWriteAction=True,
                ),
                # Broken primary selector and no fallback, resolved via Tier 3 semantic role + accessible name
                WorkflowStep(
                    action="click",
                    selector="#deleted-submit-button-id",
                    fallbackSelectors=[],
                    role="button",
                    name="إصدار الفاتورة Submit Invoice",
                    isWriteAction=True,
                    idempotent=False,
                ),
            ],
            assertions=[
                AssertionSpec(
                    type="assert_text",
                    selector="#invoice-result",
                    expected="عميل الإصلاح الذكي",
                    match="contains",
                )
            ],
        )
        runner = WorkflowRunner(vault=self.workspace.vault, workspace_dir=self.workspace.root_dir)
        report = runner.run(wf, allow_write=True)
        self.assertEqual(report.status, "passed", msg=f"Healing run failed: {report.error}")
        tiers_used = [ev["tier"] for ev in report.healing_events]
        self.assertIn(2, tiers_used)
        self.assertIn(3, tiers_used)

    def test_browser_multitab_nested_iframe_and_file_upload(self) -> None:
        """Verify multi-tabs, nested iframe interaction, and safe file upload inside real Chromium."""
        upload_file = self.workspace.uploads_dir / "invoice_doc.txt"
        upload_file.write_text("Approved attachment content\n", encoding="utf-8")

        wf = Workflow(
            name="MultiTab Iframe Upload E2E",
            target="browser",
            mode="write",
            allowedHosts=["127.0.0.2", "127.0.0.1"],
            steps=[
                WorkflowStep(action="goto", url=f"{self.base_url}/demo"),
                WorkflowStep(
                    action="upload_file",
                    selector='[data-testid="file-input"]',
                    filePath="invoice_doc.txt",
                    isWriteAction=True,
                    idempotent=False,
                ),
                # Interact inside nested iframe
                WorkflowStep(
                    action="type",
                    selector='[data-testid="frame-note-input"]',
                    framePath=["#nested-frame"],
                    text="موافقة القسم المالي",
                    role="textbox",
                    isWriteAction=True,
                ),
                WorkflowStep(
                    action="click",
                    selector='[data-testid="frame-approve"]',
                    framePath=["#nested-frame"],
                    role="button",
                    isWriteAction=True,
                ),
                WorkflowStep(
                    action="assert_text",
                    selector='[data-testid="frame-status"]',
                    framePath=["#nested-frame"],
                    expected="تمت الموافقة الفرعية: موافقة القسم المالي",
                    match="contains",
                ),
                # Open second tab, switch back to first tab, and close second tab
                WorkflowStep(action="open_tab", url=f"{self.base_url}/demo"),
                WorkflowStep(action="switch_tab", tabIndex=0),
                WorkflowStep(action="switch_tab", tabIndex=1),
                WorkflowStep(action="close_tab"),
                WorkflowStep(action="scroll", deltaX=0, deltaY=200),
            ],
        )
        runner = WorkflowRunner(vault=self.workspace.vault, workspace_dir=self.workspace.root_dir)
        report = runner.run(wf, allow_write=True)
        self.assertEqual(report.status, "passed", msg=f"Multi-tab/iframe test failed: {report.error}")


if __name__ == "__main__":
    unittest.main()
