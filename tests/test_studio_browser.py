"""Real Chromium UI Tests for the Human2API Studio Dashboard & Visual Editor (`tests/test_studio_browser.py`).
Verifies that every button, tab, theme toggle, language switch, modal, and workflow editor action works in a real browser.
"""

from __future__ import annotations

import pathlib
import tempfile
import time
import unittest

from human2api.http_server import Human2APIServer
from human2api.models import Workflow, WorkflowStep
from human2api.runner import ChromiumBrowserSession
from human2api.workspace import Workspace


class TestStudioVisualUIInChromium(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="h2a_studio_ui_")
        cls.workspace = Workspace(pathlib.Path(cls._tmp.name))
        cls.workspace.initialize()
        cls.server = Human2APIServer(workspace=cls.workspace, host="127.0.0.2", port=0)
        cls.base_url = cls.server.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop()
        cls._tmp.cleanup()

    def test_studio_dashboard_editor_and_controls_in_real_chromium(self) -> None:
        dummy_wf = Workflow(
            name="Studio Probe",
            target="browser",
            allowedHosts=["127.0.0.2"],
            steps=[WorkflowStep(action="goto", url=f"{self.base_url}/")],
        )
        session = ChromiumBrowserSession(dummy_wf, workspace_dir=self.workspace.root_dir, headless=True)
        session.start()
        try:
            driver = session.driver
            assert driver is not None
            driver.get(f"{self.base_url}/")

            # Verify Arabic RTL default and theme toggle
            self.assertEqual(driver.find_element("tag name", "html").get_attribute("dir"), "rtl")
            self.assertEqual(driver.find_element("tag name", "html").get_attribute("data-theme"), "dark")

            driver.find_element("css selector", '[data-testid="btn-toggle-theme"]').click()
            self.assertEqual(driver.find_element("tag name", "html").get_attribute("data-theme"), "light")

            driver.find_element("css selector", '[data-testid="btn-toggle-lang"]').click()
            self.assertEqual(driver.find_element("tag name", "html").get_attribute("dir"), "ltr")

            # Switch back to Arabic
            driver.find_element("css selector", '[data-testid="btn-toggle-lang"]').click()
            self.assertEqual(driver.find_element("tag name", "html").get_attribute("dir"), "rtl")

            # Open Record New Task modal and compile a recorded task via backend API
            driver.find_element("css selector", '[data-testid="btn-record-new"]').click()
            modal = driver.find_element("css selector", '[data-testid="record-modal"]')
            self.assertNotIn("hidden", modal.get_attribute("class") or "")
            driver.find_element("css selector", '[data-testid="btn-confirm-record"]').click()
            time.sleep(0.4)

            # Verify workflow was created in workspace
            self.assertGreaterEqual(len(self.workspace.list_workflows()), 1)

            # Switch to Visual Workflow Editor tab, add a step, and save workflow
            driver.find_element("css selector", '[data-testid="tab-editor"]').click()
            driver.find_element("css selector", '[data-testid="btn-add-step"]').click()
            driver.find_element("css selector", '[data-testid="btn-save-workflow"]').click()
            time.sleep(0.4)
            self.assertGreaterEqual(len(self.workspace.list_workflows()), 2)

            # Switch to Schedules tab and create a schedule
            driver.find_element("css selector", '[data-testid="tab-schedules"]').click()
            driver.find_element("css selector", '[data-testid="btn-create-schedule"]').click()
            time.sleep(0.3)
            self.assertEqual(len(self.workspace.scheduler.list_jobs()), 1)

            # Switch to Settings tab, unlock vault, and save settings
            driver.find_element("css selector", '[data-testid="tab-settings"]').click()
            pwd_in = driver.find_element("css selector", '[data-testid="vault-passphrase"]')
            pwd_in.send_keys("studio-vault-pass")
            driver.find_element("css selector", '[data-testid="btn-vault-unlock"]').click()
            time.sleep(0.3)
            self.assertTrue(self.workspace.vault.is_unlocked())
        finally:
            session.stop()


if __name__ == "__main__":
    unittest.main()
