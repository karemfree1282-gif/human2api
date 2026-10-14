import pathlib, tempfile, unittest, urllib.request, json
from human2api.http_server import Human2APIServer
from human2api.workspace import Workspace

class TestHttpMcpEndpoint(unittest.TestCase):
    def test_mcp_over_http_ping_and_tools_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(pathlib.Path(tmp))
            srv = Human2APIServer(workspace=ws, host="127.0.0.1", port=0)
            base = srv.start()
            try:
                body = json.dumps({"jsonrpc": "2.0", "id": 99, "method": "ping"}).encode("utf-8")
                req = urllib.request.Request(
                    f"{base}/mcp",
                    data=body,
                    headers={"X-H2A-Token": srv.auth_token, "Content-Type": "application/json", "Host": f"127.0.0.1:{srv.port}"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    self.assertEqual(data["result"]["status"], "pong")
            finally:
                srv.stop()
