"""Local-only dashboard and optional REST API with an ephemeral CSRF token."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from . import __version__
from .models import NAME_RE, WorkflowError, input_json_schema, list_workflows, load_workflow, save_workflow, workflow_file
from .runner import run_workflow
from .marketplace import local_catalog

MAX_POST_SIZE = 256 * 1024


def openapi_schema(directory: Path, port: int = 8765) -> dict[str, Any]:
    paths: dict[str, Any] = {}
    for entry in list_workflows(directory):
        wf = load_workflow(workflow_file(directory, entry["name"]))
        paths[f"/api/run/{wf['name']}"] = {
            "post": {
                "operationId": "run_" + wf["name"],
                "summary": wf["description"],
                "security": [{"LocalToken": []}],
                "requestBody": {"required": True, "content": {"application/json": {"schema": {"type": "object", "properties": {"inputs": input_json_schema(wf), "approve": {"type": "boolean", "description": "Explicit permission to run write workflows"}, "healSelectors": {"type": "boolean", "description": "Enable local semantic recovery"}, "aiHeal": {"type": "boolean", "description": "Explicitly consent to sending sanitized UI metadata to your configured provider"}}, "required": ["inputs"], "additionalProperties": False}}}},
                "responses": {"202": {"description": "Execution accepted; poll GET /api/runs/{runId}"}, "400": {"description": "Validation error"}},
            }
        }
    return {
        "openapi": "3.1.0",
        "info": {"title": "Human2API local REST API", "version": __version__, "description": "Only listen on loopback. Send X-H2A-Token for all API operations. Write workflows require approve:true."},
        "servers": [{"url": f"http://127.0.0.1:{port}"}],
        "components": {"securitySchemes": {"LocalToken": {"type": "apiKey", "in": "header", "name": "X-H2A-Token"}}},
        "paths": paths,
    }


class Human2APIServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address: tuple[str, int], workflows: Path, **kwargs: Any) -> None:
        self.workflows = workflows.resolve()
        self.token = secrets.token_urlsafe(32)
        self.runs: dict[str, dict[str, Any]] = {}
        self.recorder: subprocess.Popen[str] | None = None
        self.recorder_error: str | None = None
        self.lock = threading.Lock()
        super().__init__(address, RequestHandler, **kwargs)


class RequestHandler(BaseHTTPRequestHandler):
    server: Human2APIServer
    def log_message(self, fmt: str, *args: Any) -> None:
        # No POST payloads, credentials, or workflow inputs are logged.
        sys.stderr.write("h2a-http: " + (fmt % args) + "\n")

    def _json(self, code: int, value: Any) -> None:
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _asset(self, name: str, content_type: str) -> None:
        data = files("human2api").joinpath("static", name).read_bytes()
        if name == "dashboard.html":
            data = data.replace(b"__H2A_LOCAL_TOKEN__", self.server.token.encode("ascii"))
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _host_ok(self) -> bool:
        # Reject DNS rebinding to this developer-only service.
        host = self.headers.get("Host", "")
        port = self.server.server_address[1]
        if host not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

    def _auth_ok(self) -> bool:
        return secrets.compare_digest(self.headers.get("X-H2A-Token", ""), self.server.token)

    def _read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_POST_SIZE:
            raise WorkflowError("request body must be a nonempty JSON document below 256 KiB")
        data = json.loads(self.rfile.read(length))
        if not isinstance(data, dict):
            raise WorkflowError("request body must be a JSON object")
        return data

    def do_GET(self) -> None:
        if not self._host_ok():
            return self._json(403, {"error": "invalid Host/Origin"})
        path = urlsplit(self.path).path
        if path == "/":
            return self._asset("dashboard.html", "text/html; charset=utf-8")
        if path == "/app.css":
            return self._asset("app.css", "text/css; charset=utf-8")
        if path == "/app.js":
            return self._asset("app.js", "application/javascript; charset=utf-8")
        if path == "/demo.js":
            return self._asset("demo.js", "application/javascript; charset=utf-8")
        if path == "/demo":
            return self._asset("demo.html", "text/html; charset=utf-8")
        if path == "/demo.css":
            return self._asset("demo.css", "text/css; charset=utf-8")
        if path == "/health":
            return self._json(200, {"status": "ok", "version": __version__})
        if not path.startswith("/api/") or not self._auth_ok():
            return self._json(401, {"error": "invalid API token"})
        try:
            if path == "/api/platforms":
                import importlib.util
                import shutil
                return self._json(200, {"browser": {"available": True}, "desktop": {"dependencyAvailable": importlib.util.find_spec("pyautogui") is not None}, "android": {"adbInstalled": shutil.which("adb") is not None}, "aiHealing": {"optInOnly": True}})
            if path == "/api/catalog":
                return self._json(200, {"packages": local_catalog(self.server.workflows.parent / "catalog")})
            if path == "/api/workflows":
                return self._json(200, {"workflows": list_workflows(self.server.workflows)})
            if path == "/api/openapi.json":
                return self._json(200, openapi_schema(self.server.workflows, self.server.server_address[1]))
            if path.startswith("/api/workflows/"):
                name = unquote(path.removeprefix("/api/workflows/"))
                return self._json(200, load_workflow(workflow_file(self.server.workflows, name)))
            if path.startswith("/api/runs/"):
                run_id = path.removeprefix("/api/runs/")
                with self.server.lock:
                    status = self.server.runs.get(run_id)
                if status is None:
                    return self._json(404, {"error": "unknown run"})
                return self._json(200, status)
            if path == "/api/recorder":
                proc = self.server.recorder
                return self._json(200, {"running": proc is not None and proc.poll() is None, "exitCode": None if proc is None else proc.poll(), "message": self.server.recorder_error})
        except (WorkflowError, FileNotFoundError, OSError) as exc:
            return self._json(400, {"error": str(exc)[:300]})
        return self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if not self._host_ok():
            return self._json(403, {"error": "invalid Host/Origin"})
        if not self.path.startswith("/api/") or not self._auth_ok():
            return self._json(401, {"error": "invalid API token"})
        try:
            body = self._read_body()
            path = urlsplit(self.path).path
            if path.startswith("/api/run/"):
                name = unquote(path.removeprefix("/api/run/"))
                workflow = load_workflow(workflow_file(self.server.workflows, name))
                approve = body.get("approve") is True
                if workflow.get("permissions", "write") == "write" and not approve:
                    raise WorkflowError("write workflow requires approve:true")
                run_id = secrets.token_hex(6)
                with self.server.lock:
                    self.server.runs[run_id] = {"state": "running", "workflow": name, "createdAt": int(time.time())}
                def task() -> None:
                    try:
                        result = run_workflow(workflow, body.get("inputs") or {}, approve_writes=approve, artifacts_dir=self.server.workflows.parent / "runs", heal_selectors=body.get("healSelectors") is True or body.get("aiHeal") is True, ai_heal=body.get("aiHeal") is True)
                        status = {"state": "completed", "result": result}
                    except (WorkflowError, ValueError, OSError) as exc:
                        status = {"state": "failed", "error": str(exc)[:600]}
                    with self.server.lock:
                        self.server.runs[run_id] = status
                threading.Thread(target=task, daemon=True).start()
                return self._json(202, {"runId": run_id, "state": "running"})
            if path.startswith("/api/save/"):
                name = unquote(path.removeprefix("/api/save/"))
                if body.get("name") != name:
                    raise WorkflowError("workflow name must match route")
                path_out = workflow_file(self.server.workflows, name)
                with self.server.lock:
                    save_workflow(path_out, body)
                return self._json(200, {"saved": True, "name": name})
            if path == "/api/record":
                url = body.get("url")
                name = body.get("name")
                if not isinstance(name, str) or not NAME_RE.fullmatch(name):
                    raise WorkflowError("invalid workflow name")
                if not isinstance(url, str) or urlsplit(url).scheme not in {"http", "https"} or not urlsplit(url).hostname:
                    raise WorkflowError("enter a valid HTTP(S) URL")
                if workflow_file(self.server.workflows, name).exists():
                    raise WorkflowError("workflow name already exists; choose a new name")
                if self.server.recorder and self.server.recorder.poll() is None:
                    raise WorkflowError("recorder already running")
                cmd = [sys.executable, "-m", "human2api", "record", url, "--name", name, "--directory", str(self.server.workflows)]
                self.server.recorder = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return self._json(202, {"started": True, "message": "Use Stop & save in the new Chromium window"})
            return self._json(404, {"error": "not found"})
        except (WorkflowError, ValueError, OSError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)[:300]})


def make_server(workflows: Path, port: int = 8765) -> Human2APIServer:
    workflows.mkdir(parents=True, exist_ok=True)
    return Human2APIServer(("127.0.0.1", port), workflows)
