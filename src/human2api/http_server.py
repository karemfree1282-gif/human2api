"""Hardened Local REST API, Marketplace HTTPS Service, and Built-in Demo App Server."""

from __future__ import annotations

import base64
import http.server
import json
import pathlib
import secrets
import socketserver
import ssl
import threading
import time
import urllib.parse
import uuid
from typing import Any, Dict, List, Optional, Tuple

from human2api import __version__
from human2api.contracts import redact_secrets
from human2api.editor import VisualWorkflowEditor, compute_workflow_etag
from human2api.execution import CancellationToken
from human2api.mcp_server import MCPServer
from human2api.models import Workflow
from human2api.recorder import WorkflowRecorder
from human2api.runner import WorkflowRunner
from human2api.server_limits import DeviceLeaseManager, RateLimiter
from human2api.workspace import Workspace

SENSITIVE_SINGLETON_HEADERS = {
    "host",
    "origin",
    "authorization",
    "x-h2a-token",
    "x-local-token",
    "content-length",
    "transfer-encoding",
}

ALLOWED_LOOPBACK_HOSTS = {"127.0.0.1", "127.0.0.2", "localhost", "[::1]", "::1"}


def _safe_workflow_path(workspace: Workspace, untrusted_name: str) -> pathlib.Path:
    """Resolve one workflow filename only; never load/delete outside workflows/."""
    name = urllib.parse.unquote(str(untrusted_name))
    if not name or name in (".", "..") or any(ch in name for ch in ("/", "\\", "\x00")):
        raise ValueError("Invalid workflow filename")
    if not all(c.isalnum() or c in "._-" for c in name):
        raise ValueError("Invalid workflow filename")
    if not name.endswith(".json"):
        name += ".json"
    candidate = (workspace.workflows_dir / name).resolve()
    if candidate.parent != workspace.workflows_dir.resolve():
        raise ValueError("Workflow path must stay inside workflows directory")
    return candidate

DEMO_APP_HTML = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8" />
  <title>منصة الفواتير التجريبية - Human2API Demo Portal</title>
  <style>
    body { font-family: sans-serif; margin: 24px; background: #f8fafc; color: #0f172a; }
    .card { background: #fff; padding: 20px; border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); max-width: 680px; }
    label { display: block; margin-top: 12px; font-weight: bold; }
    input, select, button { margin-top: 6px; padding: 8px 12px; font-size: 14px; width: 100%; box-sizing: border-box; }
    button { background: #2563eb; color: #fff; border: none; border-radius: 6px; cursor: pointer; font-weight: bold; margin-top: 14px; }
    #invoice-result { margin-top: 16px; padding: 12px; background: #ecfdf5; border: 1px solid #10b981; border-radius: 6px; display: none; }
    iframe { width: 100%; height: 110px; border: 1px solid #cbd5e1; margin-top: 12px; border-radius: 6px; }
  </style>
</head>
<body>
  <div class="card">
    <h1 id="demo-heading">بوابة الفواتير المعتمدة - Authorized Invoice Demo</h1>
    <label for="customer-name">اسم العميل (Customer Name)</label>
    <input id="customer-name" name="customer_name" data-testid="customer-input" placeholder="أدخل اسم العميل" value="" />

    <label for="invoice-amount">قيمة الفاتورة (Amount)</label>
    <input id="invoice-amount" name="invoice_amount" data-testid="amount-input" placeholder="100.00" value="" />

    <label for="currency-select">العملة (Currency)</label>
    <select id="currency-select" name="currency" data-testid="currency-select">
      <option value="USD">USD</option>
      <option value="EUR">EUR</option>
      <option value="EGP">EGP</option>
      <option value="SAR">SAR</option>
    </select>

    <label for="api-password">كلمة المرور السرية (API Password)</label>
    <input id="api-password" name="api_password" type="password" autocomplete="current-password" data-testid="password-input" placeholder="Secret Password" />

    <label for="attachment-file">مرفق الفاتورة (Upload File)</label>
    <input id="attachment-file" name="attachment" type="file" data-testid="file-input" />

    <button id="submit-invoice-btn" data-testid="submit-invoice" type="submit" aria-label="إصدار الفاتورة Submit Invoice"
      onclick="
        const c = document.getElementById('customer-name').value || 'Guest';
        const a = document.getElementById('invoice-amount').value || '0';
        const cur = document.getElementById('currency-select').value || 'USD';
        const res = document.getElementById('invoice-result');
        res.style.display = 'block';
        res.innerText = 'تم إصدار الفاتورة بنجاح للعميل: ' + c + ' بمبلغ ' + a + ' ' + cur;
      ">إصدار الفاتورة (Submit Invoice)</button>

    <a id="Download-Receipt-Link" data-testid="download-receipt" href="/demo/receipt.txt" download="receipt.txt" style="display:inline-block;margin-top:10px;">تحميل الإيصال (Download Receipt)</a>
    <a id="external-evil-link" href="https://untrusted-external.example.com/phish" style="display:inline-block;margin-top:10px;margin-right:16px;">رابط خارجي غير مصرح</a>

    <div id="invoice-result" data-testid="invoice-result" role="status"></div>

    <iframe id="nested-frame" src="/demo/frame"></iframe>
  </div>
</body>
</html>
"""

DEMO_FRAME_HTML = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<body>
  <div id="frame-box">
    <input id="frame-note" data-testid="frame-note-input" placeholder="ملاحظة داخل الإطار الفرعي" />
    <button id="frame-approve-btn" data-testid="frame-approve" onclick="document.getElementById('frame-status').innerText='تمت الموافقة الفرعية: ' + document.getElementById('frame-note').value">اعتماد الفرعي</button>
    <span id="frame-status" data-testid="frame-status">قيد الانتظار</span>
  </div>
</body>
</html>
"""


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class Human2APIServer:
    """Local loopback REST API + Visual Studio + Marketplace Server with CSRF, DNS Rebinding, and Header Smuggling defenses."""

    def __init__(
        self,
        workspace: Workspace,
        host: str = "127.0.0.1",
        port: int = 0,
        auth_token: Optional[str] = None,
        rate_limiter: Optional[RateLimiter] = None,
        ssl_context: Optional[ssl.SSLContext] = None,
        runner: Optional[WorkflowRunner] = None,
    ) -> None:
        if host not in ALLOWED_LOOPBACK_HOSTS:
            raise ValueError(f"Human2APIServer must bind to a loopback address, got {host!r}")
        self.workspace = workspace
        self.workspace.initialize()
        self.host = host
        self.port = port
        self.auth_token = auth_token or f"h2atok_{secrets.token_urlsafe(24)}"
        self.rate_limiter = rate_limiter or RateLimiter()
        self.lease_manager = DeviceLeaseManager()
        self.ssl_context = ssl_context
        self.runner = runner or WorkflowRunner(vault=self.workspace.vault, workspace_dir=self.workspace.root_dir)
        self.mcp = MCPServer(workspace=self.workspace, runner=self.runner)
        self._active_runs: Dict[str, Dict[str, Any]] = {}
        self._runs_lock = threading.RLock()
        self._httpd: Optional[ThreadedHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def base_url(self) -> str:
        scheme = "https" if self.ssl_context else "http"
        return f"{scheme}://{self.host}:{self.port}"

    def start(self) -> str:
        server_ref = self

        class RequestHandler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: Any) -> None:
                pass

            def _send_json(self, status_code: int, payload: Dict[str, Any]) -> None:
                secrets_set = (
                    server_ref.workspace.vault.all_secret_values()
                    if server_ref.workspace.vault.is_unlocked()
                    else set()
                )
                raw_str = json.dumps(payload, ensure_ascii=False)
                safe_str = redact_secrets(raw_str, secrets_set)
                body = safe_str.encode("utf-8")
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "SAMEORIGIN")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)

            def _send_bytes(self, status_code: int, content_type: str, data: bytes) -> None:
                self.send_response(status_code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(data)

            def _validate_headers_and_host(self) -> Tuple[bool, int, str]:
                # 1. Reject duplicate sensitive headers (HTTP header smuggling / identity ambiguity)
                seen_counts: Dict[str, int] = {}
                for k, _ in self.headers.items():
                    kl = k.lower().strip()
                    seen_counts[kl] = seen_counts.get(kl, 0) + 1
                    if kl in SENSITIVE_SINGLETON_HEADERS and seen_counts[kl] > 1:
                        return False, 400, f"Duplicate sensitive HTTP header rejected: {k}"

                if "transfer-encoding" in seen_counts:
                    return False, 400, "Ambiguous Transfer-Encoding framing is rejected on local loopback API."

                # 2. Prevent DNS Rebinding via strict Host header check
                host_hdr = (self.headers.get("Host") or "").strip().lower()
                if not host_hdr:
                    return False, 400, "Missing Host header."
                host_only = host_hdr.split(":")[0] if not host_hdr.startswith("[") else host_hdr.split("]")[0] + "]"
                if host_only not in ALLOWED_LOOPBACK_HOSTS:
                    return False, 403, f"Host header {host_hdr!r} blocked by DNS Rebinding protection."

                # 3. Prevent cross-site Origin CSRF
                origin_hdr = (self.headers.get("Origin") or "").strip()
                if origin_hdr:
                    parsed_orig = urllib.parse.urlparse(origin_hdr)
                    orig_host = (parsed_orig.hostname or "").lower()
                    if orig_host not in ALLOWED_LOOPBACK_HOSTS:
                        return False, 403, f"Cross-origin request from {origin_hdr!r} blocked by CSRF policy."

                return True, 200, "ok"

            def _check_auth(self) -> bool:
                auth_hdr = (self.headers.get("Authorization") or "").strip()
                token_hdr = (self.headers.get("X-H2A-Token") or self.headers.get("X-Local-Token") or "").strip()
                candidate = ""
                if auth_hdr.lower().startswith("bearer "):
                    candidate = auth_hdr[7:].strip()
                elif token_hdr:
                    candidate = token_hdr
                if not candidate:
                    return False
                return secrets.compare_digest(candidate, server_ref.auth_token)

            def _read_json_body(self) -> Tuple[Optional[Dict[str, Any]], Optional[Tuple[int, str]]]:
                cl_str = self.headers.get("Content-Length")
                if not cl_str:
                    return {}, None
                try:
                    cl = int(cl_str)
                except ValueError:
                    return None, (400, "Invalid Content-Length.")
                if cl < 0 or cl > server_ref.rate_limiter.max_body_bytes:
                    return None, (413, f"Request body exceeds limit ({server_ref.rate_limiter.max_body_bytes} bytes).")
                raw = self.rfile.read(cl) if cl > 0 else b"{}"
                try:
                    parsed = json.loads(raw.decode("utf-8"))
                    if not isinstance(parsed, dict):
                        return None, (400, "JSON body must be an object.")
                    return parsed, None
                except Exception as exc:
                    return None, (400, f"Malformed JSON payload: {exc}")

            def _dispatch(self, method: str) -> None:
                client_ip = self.client_address[0] if self.client_address else "127.0.0.1"
                if not server_ref.rate_limiter.try_enter_request(client_ip):
                    self._send_json(429, {"error": "Rate limit or concurrency limit exceeded."})
                    return
                try:
                    ok, code, msg = self._validate_headers_and_host()
                    if not ok:
                        self._send_json(code, {"error": msg})
                        return

                    parsed_url = urllib.parse.urlparse(self.path)
                    path = parsed_url.path
                    query = urllib.parse.parse_qs(parsed_url.query)

                    # Public unauthenticated demo & static UI endpoints
                    if method == "GET" and path == "/demo":
                        self._send_bytes(200, "text/html; charset=utf-8", DEMO_APP_HTML.encode("utf-8"))
                        return
                    if method == "GET" and path == "/demo/frame":
                        self._send_bytes(200, "text/html; charset=utf-8", DEMO_FRAME_HTML.encode("utf-8"))
                        return
                    if method == "GET" and path == "/demo/receipt.txt":
                        self._send_bytes(200, "text/plain; charset=utf-8", b"Human2API Verified Receipt #2026-OK\n")
                        return
                    if method == "GET" and path in ("/", "/index.html", "/studio"):
                        static_dir = pathlib.Path(__file__).parent / "static"
                        html_file = static_dir / "index.html"
                        html_text = html_file.read_text(encoding="utf-8").replace("__H2A_BOOTSTRAP_TOKEN__", server_ref.auth_token)
                        self._send_bytes(200, "text/html; charset=utf-8", html_text.encode("utf-8"))
                        return
                    if method == "GET" and path.startswith("/static/"):
                        rel = path[len("/static/") :]
                        if ".." in rel or "/" in rel:
                            self._send_json(403, {"error": "Forbidden static path."})
                            return
                        static_file = (pathlib.Path(__file__).parent / "static" / rel).resolve()
                        if not static_file.exists():
                            self._send_json(404, {"error": "Static asset not found."})
                            return
                        ctype = "text/css; charset=utf-8" if rel.endswith(".css") else (
                            "application/javascript; charset=utf-8" if rel.endswith(".js") else "text/plain; charset=utf-8"
                        )
                        self._send_bytes(200, ctype, static_file.read_bytes())
                        return

                    # Marketplace public read endpoints (catalog & package download)
                    if method == "GET" and path == "/api/v1/marketplace/packages":
                        q = (query.get("q") or [""])[0]
                        cat = (query.get("category") or [None])[0]
                        tgt = (query.get("target") or [None])[0]
                        pkgs = server_ref.workspace.registry.search_packages(query=q, category=cat, target=tgt)
                        self._send_json(200, {"packages": pkgs})
                        return

                    if method == "GET" and path == "/api/v1/marketplace/download":
                        tool_id = (query.get("tool_id") or [""])[0]
                        ver = (query.get("version") or [None])[0]
                        try:
                            zip_bytes, _ = server_ref.workspace.registry.download_package_bytes(tool_id, ver)
                            self._send_bytes(200, "application/zip", zip_bytes)
                        except KeyError as exc:
                            self._send_json(404, {"error": str(exc)})
                        except PermissionError as exc:
                            self._send_json(410, {"error": str(exc)})
                        return

                    # All other API endpoints require valid Bearer / X-H2A-Token authentication
                    if not self._check_auth():
                        self._send_json(401, {"error": "Unauthorized: missing or invalid local API token."})
                        return

                    if method == "GET" and path == "/api/v1/health":
                        self._send_json(
                            200,
                            {
                                "status": "ok",
                                "version": __version__,
                                "vault_unlocked": server_ref.workspace.vault.is_unlocked(),
                            },
                        )
                        return

                    if method == "GET" and path == "/api/v1/status":
                        self._send_json(
                            200,
                            {
                                "version": __version__,
                                "workflows_count": len(server_ref.workspace.list_workflows()),
                                "installed_packages_count": len(server_ref.workspace.marketplace.list_installed()),
                                "schedules_count": len(server_ref.workspace.scheduler.list_jobs()),
                                "history_count": len(server_ref.workspace.history.list_runs()),
                                "vault_unlocked": server_ref.workspace.vault.is_unlocked(),
                                "settings": server_ref.workspace.get_config(),
                            },
                        )
                        return

                    if method == "GET" and path == "/api/v1/workflows":
                        self._send_json(200, {"workflows": server_ref.workspace.list_workflows()})
                        return

                    if method == "POST" and path == "/api/v1/workflows":
                        body, err = self._read_json_body()
                        if err:
                            self._send_json(err[0], {"error": err[1]})
                            return
                        try:
                            wf = Workflow.from_dict(body or {})
                            safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in wf.name.lower()).strip("_") or "workflow"
                            out_path = server_ref.workspace.workflows_dir / f"{safe_name}.json"
                            wf.save(out_path)
                            self._send_json(
                                201,
                                {
                                    "workflow": wf.to_dict(),
                                    "filename": out_path.name,
                                    "etag": compute_workflow_etag(wf),
                                },
                            )
                        except Exception as exc:
                            self._send_json(400, {"error": str(exc)})
                        return

                    if path.startswith("/api/v1/workflows/") and method in ("PUT", "DELETE", "POST"):
                        parts = [p for p in path.split("/") if p]
                        wf_slug = urllib.parse.unquote(parts[3])
                        try:
                            wf_file = _safe_workflow_path(server_ref.workspace, wf_slug)
                        except ValueError as exc:
                            self._send_json(400, {"error": str(exc)})
                            return
                        if not wf_file.exists():
                            self._send_json(404, {"error": f"Workflow {wf_slug!r} not found."})
                            return
                        if method == "DELETE":
                            wf_file.unlink()
                            self._send_json(200, {"deleted": wf_slug})
                            return

                        body, err = self._read_json_body()
                        if err:
                            self._send_json(err[0], {"error": err[1]})
                            return
                        wf = Workflow.load(wf_file)
                        op = (body or {}).get("operation")
                        try:
                            if op == "add_step":
                                wf = VisualWorkflowEditor.add_step(wf, body.get("step") or {}, body.get("position"))
                            elif op == "delete_step":
                                wf = VisualWorkflowEditor.delete_step(wf, int(body.get("index", 0)))
                            elif op == "reorder_steps":
                                wf = VisualWorkflowEditor.reorder_steps(wf, int(body.get("fromIndex", 0)), int(body.get("toIndex", 0)))
                            elif op == "set_input":
                                wf = VisualWorkflowEditor.set_input_parameter(
                                    wf,
                                    name=str(body.get("name", "param")),
                                    input_type=str(body.get("type", "string")),
                                    description=str(body.get("description", "")),
                                    required=bool(body.get("required", True)),
                                    sensitive=bool(body.get("sensitive", False)),
                                    default=body.get("default"),
                                )
                            else:
                                wf = Workflow.from_dict(body or {})
                            wf.save(wf_file)
                            self._send_json(200, {"workflow": wf.to_dict(), "etag": compute_workflow_etag(wf)})
                        except Exception as exc:
                            self._send_json(400, {"error": str(exc)})
                        return

                    if method == "POST" and path == "/api/v1/record/compile":
                        body, err = self._read_json_body()
                        if err:
                            self._send_json(err[0], {"error": err[1]})
                            return
                        try:
                            rec = WorkflowRecorder(
                                name=str((body or {}).get("name") or "Recorded Task"),
                                target=str((body or {}).get("target") or "browser"),
                                network_policy=str((body or {}).get("networkPolicy") or "strict"),
                            )
                            for ev in (body or {}).get("events") or []:
                                rec.record_event(ev)
                            wf = rec.compile_workflow()
                            if (body or {}).get("save", True):
                                safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in wf.name.lower()).strip("_") or "recorded_task"
                                wf.save(server_ref.workspace.workflows_dir / f"{safe_name}.json")
                            self._send_json(201, {"workflow": wf.to_dict()})
                        except Exception as exc:
                            self._send_json(400, {"error": str(exc)})
                        return

                    if method == "POST" and path == "/api/v1/run":
                        body, err = self._read_json_body()
                        if err:
                            self._send_json(err[0], {"error": err[1]})
                            return
                        assert body is not None
                        try:
                            if "workflow" in body and isinstance(body["workflow"], dict):
                                wf = Workflow.from_dict(body["workflow"])
                            elif "workflowName" in body:
                                wf_name = str(body["workflowName"])
                                wf_path = _safe_workflow_path(server_ref.workspace, wf_name)
                                wf = Workflow.load(wf_path)
                            else:
                                self._send_json(400, {"error": "Provide 'workflow' object or 'workflowName'."})
                                return
                        except Exception as exc:
                            self._send_json(400, {"error": str(exc)})
                            return

                        run_id = f"run_{uuid.uuid4().hex[:12]}"
                        cancel_token = CancellationToken()
                        progress_steps: List[Dict[str, Any]] = []
                        with server_ref._runs_lock:
                            server_ref._active_runs[run_id] = {
                                "run_id": run_id,
                                "workflow_name": wf.name,
                                "status": "running",
                                "cancel_token": cancel_token,
                                "steps": progress_steps,
                                "report": None,
                            }

                        def _on_step(step_rec):
                            progress_steps.append(step_rec.to_dict())

                        run_async = bool(body.get("async", False))
                        inputs = dict(body.get("inputs") or {})
                        allow_write = bool(body.get("allowWrite", False))

                        def _exec_run():
                            local_runner = WorkflowRunner(
                                vault=server_ref.workspace.vault,
                                workspace_dir=server_ref.workspace.root_dir,
                                desktop_adapter=server_ref.runner.desktop_adapter,
                                android_adapter=server_ref.runner.android_adapter,
                                step_observer=_on_step,
                            )
                            rep = local_runner.run(
                                workflow=wf,
                                inputs=inputs,
                                allow_write=allow_write,
                                cancel_token=cancel_token,
                            )
                            secrets_set = (
                                server_ref.workspace.vault.all_secret_values()
                                if server_ref.workspace.vault.is_unlocked()
                                else set()
                            )
                            server_ref.workspace.history.record_run(rep, secret_values=secrets_set)
                            with server_ref._runs_lock:
                                server_ref._active_runs[run_id]["status"] = rep.status
                                server_ref._active_runs[run_id]["report"] = rep.to_dict(secret_values=secrets_set)
                            return rep

                        if run_async:
                            t = threading.Thread(target=_exec_run, daemon=True)
                            t.start()
                            self._send_json(202, {"run_id": run_id, "status": "running"})
                        else:
                            rep = _exec_run()
                            secrets_set = (
                                server_ref.workspace.vault.all_secret_values()
                                if server_ref.workspace.vault.is_unlocked()
                                else set()
                            )
                            code = 200 if rep.status == "passed" else (499 if rep.status == "cancelled" else 422)
                            self._send_json(code, {"run_id": run_id, "report": rep.to_dict(secret_values=secrets_set)})
                        return

                    if path.startswith("/api/v1/runs/"):
                        parts = [p for p in path.split("/") if p]
                        run_id = parts[3]
                        with server_ref._runs_lock:
                            run_entry = server_ref._active_runs.get(run_id)
                        if run_entry is None:
                            self._send_json(404, {"error": f"Run {run_id!r} not found."})
                            return
                        if method == "POST" and path.endswith("/cancel"):
                            run_entry["cancel_token"].cancel("Cancelled via REST API.")
                            self._send_json(200, {"run_id": run_id, "status": "cancelling"})
                            return
                        if method == "GET":
                            self._send_json(
                                200,
                                {
                                    "run_id": run_id,
                                    "workflow_name": run_entry["workflow_name"],
                                    "status": run_entry["status"],
                                    "steps": run_entry["steps"],
                                    "report": run_entry["report"],
                                },
                            )
                            return

                    if method == "GET" and path == "/api/v1/history":
                        self._send_json(200, {"history": server_ref.workspace.history.list_runs()})
                        return

                    if path == "/api/v1/schedules":
                        if method == "GET":
                            self._send_json(200, {"schedules": server_ref.workspace.scheduler.list_jobs()})
                            return
                        if method == "POST":
                            body, err = self._read_json_body()
                            if err:
                                self._send_json(err[0], {"error": err[1]})
                                return
                            try:
                                job = server_ref.workspace.scheduler.add_job(
                                    workflow_path=str((body or {}).get("workflowPath") or ""),
                                    workflow_name=str((body or {}).get("workflowName") or "Scheduled Workflow"),
                                    interval_seconds=int((body or {}).get("intervalSeconds", 60)),
                                    inputs=dict((body or {}).get("inputs") or {}),
                                    allow_write=bool((body or {}).get("allowWrite", True)),
                                )
                                self._send_json(201, {"schedule": job.to_dict()})
                            except Exception as exc:
                                self._send_json(400, {"error": str(exc)})
                            return

                    if path.startswith("/api/v1/schedules/"):
                        job_id = path.split("/")[4]
                        if method == "DELETE":
                            removed = server_ref.workspace.scheduler.remove_job(job_id)
                            self._send_json(200 if removed else 404, {"deleted": removed})
                            return
                        if method == "PATCH":
                            body, err = self._read_json_body()
                            if err:
                                self._send_json(err[0], {"error": err[1]})
                                return
                            try:
                                job = server_ref.workspace.scheduler.set_enabled(job_id, bool((body or {}).get("enabled", True)))
                                self._send_json(200, {"schedule": job.to_dict()})
                            except KeyError as exc:
                                self._send_json(404, {"error": str(exc)})
                            return

                    if path.startswith("/api/v1/marketplace/"):
                        body, err = self._read_json_body() if method == "POST" else ({}, None)
                        if err:
                            self._send_json(err[0], {"error": err[1]})
                            return
                        assert body is not None
                        try:
                            if method == "GET" and path == "/api/v1/marketplace/installed":
                                self._send_json(200, {"installed": server_ref.workspace.marketplace.list_installed()})
                                return
                            if method == "GET" and path == "/api/v1/marketplace/diff":
                                tid = (query.get("tool_id") or [""])[0]
                                v1 = (query.get("from") or [""])[0]
                                v2 = (query.get("to") or [""])[0]
                                self._send_json(200, {"diff": server_ref.workspace.registry.diff_versions(tid, v1, v2)})
                                return
                            if method == "POST" and path == "/api/v1/marketplace/publishers":
                                tok = server_ref.workspace.registry.register_publisher(
                                    publisher_id=str(body["publisher_id"]),
                                    display_name=str(body.get("display_name") or body["publisher_id"]),
                                    public_key_b64=str(body["public_key"]),
                                )
                                self._send_json(201, {"publisher_id": body["publisher_id"], "publisher_token": tok})
                                return
                            if method == "POST" and path == "/api/v1/marketplace/publish":
                                zip_b64 = str(body["package_zip_b64"])
                                res = server_ref.workspace.registry.publish_package(
                                    publisher_id=str(body["publisher_id"]),
                                    token=str(body["publisher_token"]),
                                    zip_bytes=base64.b64decode(zip_b64),
                                    category=str(body.get("category", "automation")),
                                )
                                self._send_json(201, {"published": res})
                                return
                            if method == "POST" and path == "/api/v1/marketplace/install":
                                rec = server_ref.workspace.marketplace.install_from_registry(
                                    tool_id=str(body["tool_id"]),
                                    version=body.get("version"),
                                    allow_privilege_expansion=bool(body.get("allowPrivilegeExpansion", False)),
                                )
                                self._send_json(200, {"installed": rec})
                                return
                            if method == "POST" and path == "/api/v1/marketplace/yank":
                                server_ref.workspace.registry.yank_package(
                                    publisher_id=str(body["publisher_id"]),
                                    token=str(body["publisher_token"]),
                                    tool_id=str(body["tool_id"]),
                                    version=str(body["version"]),
                                    reason=str(body.get("reason", "security")),
                                )
                                self._send_json(200, {"yanked": True})
                                return
                            if method == "POST" and path == "/api/v1/marketplace/reviews":
                                rev = server_ref.workspace.registry.add_review(
                                    reviewer_publisher_id=str(body["publisher_id"]),
                                    token=str(body["publisher_token"]),
                                    tool_id=str(body["tool_id"]),
                                    version=str(body["version"]),
                                    rating=int(body["rating"]),
                                    comment=str(body.get("comment", "")),
                                )
                                self._send_json(201, {"review": rev})
                                return
                            if method == "POST" and path == "/api/v1/marketplace/report":
                                rep = server_ref.workspace.registry.report_suspicious_tool(
                                    tool_id=str(body["tool_id"]),
                                    version=str(body["version"]),
                                    reporter=str(body.get("reporter", "user")),
                                    reason=str(body["reason"]),
                                )
                                self._send_json(201, {"report": rep})
                                return
                        except PermissionError as exc:
                            self._send_json(403, {"error": str(exc)})
                            return
                        except KeyError as exc:
                            self._send_json(404, {"error": str(exc)})
                            return
                        except Exception as exc:
                            self._send_json(400, {"error": str(exc)})
                            return

                    if path == "/api/v1/settings":
                        if method == "GET":
                            self._send_json(200, {"settings": server_ref.workspace.get_config()})
                            return
                        if method == "POST":
                            body, err = self._read_json_body()
                            if err:
                                self._send_json(err[0], {"error": err[1]})
                                return
                            cfg = server_ref.workspace.update_config(body or {})
                            self._send_json(200, {"settings": cfg})
                            return

                    if path.startswith("/api/v1/vault/"):
                        body, err = self._read_json_body()
                        if err:
                            self._send_json(err[0], {"error": err[1]})
                            return
                        assert body is not None
                        try:
                            if path == "/api/v1/vault/unlock":
                                server_ref.workspace.vault.unlock(str(body.get("passphrase", "")))
                                self._send_json(200, {"unlocked": True, "secrets": server_ref.workspace.vault.list_secret_names()})
                                return
                            if path == "/api/v1/vault/lock":
                                server_ref.workspace.vault.lock()
                                self._send_json(200, {"unlocked": False})
                                return
                            if path == "/api/v1/vault/secrets":
                                server_ref.workspace.vault.set_secret(str(body["name"]), str(body["value"]))
                                self._send_json(201, {"saved": body["name"], "secrets": server_ref.workspace.vault.list_secret_names()})
                                return
                        except Exception as exc:
                            self._send_json(400, {"error": str(exc)})
                            return

                    if method == "POST" and path == "/mcp":
                        body, err = self._read_json_body()
                        if err:
                            self._send_json(err[0], {"error": err[1]})
                            return
                        resp = server_ref.mcp.handle_rpc(body or {})
                        self._send_json(200, resp)
                        return

                    self._send_json(404, {"error": f"Endpoint not found: {method} {path}"})
                finally:
                    server_ref.rate_limiter.exit_request()

            def do_GET(self) -> None:
                self._dispatch("GET")

            def do_POST(self) -> None:
                self._dispatch("POST")

            def do_PUT(self) -> None:
                self._dispatch("PUT")

            def do_PATCH(self) -> None:
                self._dispatch("PATCH")

            def do_DELETE(self) -> None:
                self._dispatch("DELETE")

        self._httpd = ThreadedHTTPServer((self.host, self.port), RequestHandler)
        if self.ssl_context is not None:
            self._httpd.socket = self.ssl_context.wrap_socket(self._httpd.socket, server_side=True)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self.base_url

    def stop(self) -> None:
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:
                pass
            self._httpd = None
