import pathlib, tempfile, unittest, urllib.request, json
from human2api.http_server import Human2APIServer
from human2api.workspace import Workspace

class TestHttpMultiTargetCompile(unittest.TestCase):
    def test_record_compile_endpoint_creates_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(pathlib.Path(tmp))
            srv = Human2APIServer(workspace=ws, host="127.0.0.1", port=0)
            base = srv.start()
            try:
                payload = {
                    "name": "API Compiled Task",
                    "target": "windows-uia",
                    "save": True,
                    "events": [{"action": "click", "automation_id": "btnOk", "role": "button", "accessible_name": "OK"}],
                }
                req = urllib.request.Request(
                    f"{base}/api/v1/record/compile",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"X-H2A-Token": srv.auth_token, "Content-Type": "application/json", "Host": f"127.0.0.1:{srv.port}"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    self.assertEqual(resp.status, 201)
            finally:
                srv.stop()
