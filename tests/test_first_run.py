"""Executable first-run acceptance checks (not fabricated build receipts)."""

import importlib.util
import json
import pathlib
import shutil
import socket
import tempfile
import unittest
import urllib.request
from unittest.mock import patch

from human2api.http_server import DEMO_APP_HTML, Human2APIServer
from human2api.models import Workflow
from human2api.quickstart import ensure_local_demo
from human2api.runner import ChromiumBrowserSession, WorkflowRunner, normalize_loopback_url_for_chromium
from human2api.workspace import Workspace


class TestFirstRun(unittest.TestCase):
    def test_start_creates_demo_and_serves_authenticated_api(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Workspace(pathlib.Path(folder))
            server = Human2APIServer(workspace, host="127.0.0.1", port=0)
            url = server.start()
            try:
                demo = ensure_local_demo(workspace, url)
                self.assertEqual(demo.steps[0].url, url + "/demo")
                self.assertEqual(len(workspace.list_workflows()), 1)
                def get(path, headers=None):
                    request = urllib.request.Request(url + path, headers=headers or {})
                    with urllib.request.urlopen(request, timeout=3) as response:
                        return response.status, response.read()
                status, page = get("/")
                self.assertEqual(status, 200)
                self.assertIn(b"Human2API", page)
                status, body = get("/api/v1/health", {"X-H2A-Token": server.auth_token})
                self.assertEqual(json.loads(body)["status"], "ok")
                status, body = get("/api/v1/workflows", {"X-H2A-Token": server.auth_token})
                self.assertEqual(len(json.loads(body)["workflows"]), 1)
                status, body = get("/demo")
                self.assertIn(b"customer-name", body)
            finally:
                server.stop()

    def test_restart_repairs_demo_port_without_deleting_user_steps(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Workspace(pathlib.Path(folder))
            workspace.initialize()
            demo = ensure_local_demo(workspace, "http://127.0.0.1:11111")
            demo.steps.append(demo.steps[-1])
            demo.save(workspace.workflows_dir / "demo_invoice.json")
            restarted = ensure_local_demo(workspace, "http://127.0.0.1:22222")
            self.assertEqual(restarted.steps[0].url, "http://127.0.0.1:22222/demo")
            self.assertEqual(len(restarted.steps), 6)

    def test_loopback_mapping_requires_a_real_target_listener(self):
        # Old behavior rewrote every 127.0.0.1 URL to 127.0.0.2,
        # breaking working local app servers on Windows and Linux.
        def connection_for(available):
            def fake_create(address, timeout=None):
                if address[0] not in available:
                    raise OSError("Connection refused")
                return socket.socket()
            return fake_create
        with patch("human2api.runner.socket.create_connection", side_effect=connection_for({"127.0.0.1"})):
            self.assertEqual(normalize_loopback_url_for_chromium("http://127.0.0.1:8123/demo"),
                             "http://127.0.0.1:8123/demo")
        with patch("human2api.runner.socket.create_connection", side_effect=connection_for({"127.0.0.2"})):
            self.assertEqual(normalize_loopback_url_for_chromium("http://127.0.0.1:8123/demo"),
                             "http://127.0.0.2:8123/demo")
        with patch("human2api.runner.socket.create_connection", side_effect=connection_for(set())):
            self.assertEqual(normalize_loopback_url_for_chromium("http://localhost:8123/demo"),
                             "http://localhost:8123/demo")
        self.assertEqual(normalize_loopback_url_for_chromium("https://example.com/page"),
                         "https://example.com/page")

    @unittest.skipUnless(importlib.util.find_spec("playwright") and (
        shutil.which("chromium") or shutil.which("google-chrome") or shutil.which("chromium-browser")
    ), "Optional Playwright/Chromium browser integration dependencies unavailable")
    def test_real_chromium_fallback_executes_dom_workflow(self):
        # The managed test environment disallows browser navigation to local
        # servers; set_content still tests real Chromium DOM actions and the
        # full runner/healer/parameter/assertion path, without fake mocks.
        from human2api.playwright_driver import PlaywrightDriver
        workflow = Workflow.from_dict({
            "name": "First Run Chromium DOM",
            "target": "browser",
            "mode": "write",
            "steps": [
                {"action": "type", "selector": "#customer-name", "text": "شركة التشغيل", "isWriteAction": True},
                {"action": "type", "selector": "#invoice-amount", "text": "123", "isWriteAction": True},
                {"action": "click", "selector": "#submit-invoice-btn", "isWriteAction": True},
                {"action": "assert_text", "selector": "#invoice-result", "expected": "شركة التشغيل"},
            ],
        })
        def launch_loaded_page(session):
            session.downloads_dir.mkdir(parents=True, exist_ok=True)
            session.driver = PlaywrightDriver(session.downloads_dir, headless=True)
            session._engine = "playwright"
            session.driver._page.set_content(DEMO_APP_HTML)
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(ChromiumBrowserSession, "start", launch_loaded_page):
                report = WorkflowRunner(workspace_dir=pathlib.Path(folder)).run(workflow, allow_write=True)
            self.assertEqual(report.status, "passed", report.error)
            self.assertEqual(report.assertions_passed, 1)
            self.assertEqual(len(report.steps), 4)


if __name__ == "__main__":
    unittest.main()


class TestWorkflowFilenameValidation(unittest.TestCase):
    def test_reject_path_traversal_from_run_api(self):
        import urllib.error
        with tempfile.TemporaryDirectory() as folder:
            workspace = Workspace(pathlib.Path(folder))
            server = Human2APIServer(workspace, host="127.0.0.1", port=0)
            url = server.start()
            try:
                for malicious in ("../outside", "../../secrets", "folder/../workflows", "x\\y"):
                    body = json.dumps({"workflowName": malicious}).encode()
                    req = urllib.request.Request(url + "/api/v1/run", data=body, method="POST", headers={
                        "X-H2A-Token": server.auth_token, "Content-Type": "application/json",
                    })
                    with self.assertRaises(urllib.error.HTTPError) as ctx:
                        urllib.request.urlopen(req, timeout=3)
                    self.assertEqual(ctx.exception.code, 400)
            finally:
                server.stop()
