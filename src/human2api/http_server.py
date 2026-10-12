"""Local-only dashboard and optional REST API with an ephemeral CSRF token."""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
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
from .models import NAME_RE, WorkflowError, input_json_schema, list_workflows, load_workflow, save_workflow, workflow_file, validate_inputs
from .runner import run_workflow
from .execution import RunCancelled
from .server_limits import BoundedHTTPServer, unique_security_headers
from .marketplace import local_catalog, remote_catalog
from .history import RunJournal
from .scheduler import LocalScheduler

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
                "responses": {"202": {"description": "Execution accepted; poll GET /api/runs/{runId}"}, "400": {"description": "Validation error"}, "429": {"description": "All local execution slots are busy"}},
            }
        }
    paths["/api/runs/{runId}/cancel"] = {
        "post": {"operationId": "cancel_run", "summary": "Request cooperative cancellation of an active run",
                 "security": [{"LocalToken": []}], "parameters": [{"name": "runId", "in": "path", "required": True, "schema": {"type": "string"}}],
                 "responses": {"202": {"description": "Cancellation requested"}, "409": {"description": "Run already finished"}}}}
    # Operational routes are documented alongside each typed workflow tool.
    from .contracts import workflow_schema
    for route, label in {
        "/api/workflows":"List installed workflows", "/api/history":"Metadata-only run history",
        "/api/schedules":"List enabled schedules", "/api/platforms":"Platform capability probes",
        "/api/catalog":"List local packages", "/api/catalog/remote":"Query public JSON catalog",
        "/api/recorder":"Recorder status", "/api/openapi.json":"This OpenAPI definition",
    }.items():
        paths[route] = {"get":{"summary":label,"security":[{"LocalToken":[]}],"responses":{"200":{"description":"JSON response"},"401":{"description":"Invalid token"}}}}
    for route, label, parameter in (
        ("/api/runs/{runId}","Live status or metadata-only history","runId"),
        ("/api/editor/workflows/{name}","Workflow and current revision","name"),
        ("/api/workflows/{name}","Inspect workflow","name"),
    ):
        paths[route] = {"get":{"summary":label,"security":[{"LocalToken":[]}],
            "parameters":[{"name":parameter,"in":"path","required":True,"schema":{"type":"string"}}],
            "responses":{"200":{"description":"Current JSON data"},"404":{"description":"Not found"}}}}
    definition = workflow_schema()
    definition.pop("$id", None)
    def embed_references(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "$ref" and isinstance(child, str) and child.startswith("#/$defs/"):
                    value[key] = "#/components/schemas/Workflow/$defs/" + child.removeprefix("#/$defs/")
                else:
                    embed_references(child)
        elif isinstance(value, list):
            for child in value:
                embed_references(child)
    embed_references(definition)
    for route, label in (("/api/editor/validate","Validate only; never execute"),("/api/editor/save/{name}","Optimistic-concurrency save with revision backup")):
        operation = {"summary":label,"security":[{"LocalToken":[]}],"requestBody":{"required":True,"content":{"application/json":{"schema":{"$ref":"#/components/schemas/Workflow"}}}},
            "responses":{"200":{"description":"Validation or new revision"},"400":{"description":"Invalid definition"},"409":{"description":"Conflicting edit"},"428":{"description":"Missing If-Match revision"}}}
        if "{name}" in route:
            operation["parameters"]=[{"name":"name","in":"path","required":True,"schema":{"type":"string"}},
                {"name":"If-Match","in":"header","required":True,"schema":{"type":"string"},"description":"Revision from GET; use new to create"}]
        paths[route]={"post":operation}
    return {
        "openapi": "3.1.0",
        "info": {"title": "Human2API local REST API", "version": __version__, "description": "Only listen on loopback. Send X-H2A-Token for all API operations. Write workflows require approve:true."},
        "servers": [{"url": f"http://127.0.0.1:{port}"}],
        "components": {"securitySchemes": {"LocalToken": {"type": "apiKey", "in": "header", "name": "X-H2A-Token"}}, "schemas": {"Workflow": definition}},
        "paths": paths,
    }


class Human2APIServer(BoundedHTTPServer):
    daemon_threads = True
    def __init__(self, address: tuple[str, int], workflows: Path, **kwargs: Any) -> None:
        self.workflows = workflows.resolve()
        self.token = secrets.token_urlsafe(32)
        self.runs: dict[str, dict[str, Any]] = {}
        self.cancellations: dict[str, threading.Event] = {}
        self.execution_slots = threading.BoundedSemaphore(2)
        self.journal = RunJournal(self.workflows.parent / ".h2a" / "history.db")
        self.recorder: subprocess.Popen[str] | None = None
        self.recorder_error: str | None = None
        self.lock = threading.Lock()
        super().__init__(address, RequestHandler, **kwargs)

    def purge_results(self) -> None:
        """Call while holding lock; the durable journal contains metadata only."""
        completed = sorted(((k, v) for k, v in self.runs.items() if v.get("state") in {"completed", "failed", "cancelled"}), key=lambda x: x[1].get("finishedAt", 0), reverse=True)
        keep = {key for key, _ in completed[:100]}
        now = time.time()
        for key, item in completed:
            if key not in keep or now - item.get("finishedAt", 0) > 3600:
                self.runs.pop(key, None)


class RequestHandler(BaseHTTPRequestHandler):
    server: Human2APIServer
    def log_message(self, fmt: str, *args: Any) -> None:
        # No POST payloads, credentials, or workflow inputs are logged.
        return  # Request URLs can contain private identifiers; do not log them.

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
        if name in {"dashboard.html", "editor.html"}:
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
        if not unique_security_headers(self.headers):
            return False
        # Reject DNS rebinding to this developer-only service.
        host = self.headers.get("Host", "")
        port = self.server.server_address[1]
        if host not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

    def _auth_ok(self) -> bool:
        return secrets.compare_digest(self.headers.get("X-H2A-Token", "").encode("utf-8"), self.server.token.encode("utf-8"))

    def _read_body(self) -> dict[str, Any]:
        if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1:
            raise WorkflowError("one Content-Length and no Transfer-Encoding are required")
        self.connection.settimeout(15)
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
        if path == "/editor":
            return self._asset("editor.html", "text/html; charset=utf-8")
        if path == "/editor.js":
            return self._asset("editor.js", "application/javascript; charset=utf-8")
        if path == "/editor.css":
            return self._asset("editor.css", "text/css; charset=utf-8")
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
            if path.startswith("/api/editor/workflows/"):
                from .editor import revision
                name = unquote(path.removeprefix("/api/editor/workflows/"))
                p = workflow_file(self.server.workflows, name)
                with self.server.lock:
                    return self._json(200, {"workflow": load_workflow(p), "revision": revision(p)})
            if path == "/api/platforms":
                import importlib.util
                import shutil
                return self._json(200, {"browser": {"available": True}, "desktop": {"dependencyAvailable": importlib.util.find_spec("pyautogui") is not None}, "android": {"adbInstalled": shutil.which("adb") is not None}, "nativeAccessibility": {"windows": "UIA", "macos": "AX", "linux": "AT-SPI", "requiresPermission": True}, "windowsUIA": {"supportedOnWindows": True, "requiresExtra": "accessibility"}, "aiHealing": {"optInOnly": True}})
            if path == "/api/catalog":
                return self._json(200, {"packages": local_catalog(self.server.workflows.parent / "catalog")})
            if path == "/api/catalog/remote":
                return self._json(200, {"packages": remote_catalog()})
            if path == "/api/history":
                return self._json(200, {"history": self.server.journal.list()})
            if path == "/api/schedules":
                return self._json(200, {"schedules": LocalScheduler(self.server.workflows).list(), "workerRequired": True})
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
                    self.server.purge_results()
                    status = self.server.runs.get(run_id)
                if status is None:
                    # After a server restart, only non-sensitive run metadata remains.
                    record = self.server.journal.get(run_id)
                    if record is None:
                        return self._json(404, {"error": "unknown run"})
                    return self._json(200, {**record, "summaryOnly": True})
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
            if path == "/api/editor/validate":
                from .editor import inspect_definition
                return self._json(200, inspect_definition(body))
            if path.startswith("/api/editor/save/"):
                from .editor import save_revision, EditConflict
                expected = self.headers.get("If-Match")
                if expected is None:
                    return self._json(428, {"error": "If-Match revision is required"})
                name = unquote(path.removeprefix("/api/editor/save/"))
                try:
                    with self.server.lock:
                        rev = save_revision(self.server.workflows, name, body, expected)
                    return self._json(200, {"saved": True, "revision": rev})
                except EditConflict as exc:
                    return self._json(409, {"error": str(exc)})
            if path == "/api/schedules/add":
                name = body.get("name")
                minutes = body.get("everyMinutes")
                data_path = body.get("dataFile")
                if data_path is not None and (not isinstance(data_path, str) or not 0 < len(data_path) <= 4096):
                    raise WorkflowError("dataFile must be a local file path")
                added = LocalScheduler(self.server.workflows).add(name, every_minutes=minutes,
                    approve_writes=body.get("approve") is True,
                    data_file=Path(data_path) if data_path is not None else None)
                return self._json(201, {"schedule": added})
            if path == "/api/schedules/remove":
                name = body.get("name")
                if not isinstance(name, str) or not NAME_RE.fullmatch(name):
                    raise WorkflowError("invalid schedule name")
                LocalScheduler(self.server.workflows).remove(name)
                return self._json(200, {"removed": name})
            if path.startswith("/api/runs/") and path.endswith("/cancel"):
                run_id = path[len("/api/runs/"):-len("/cancel")]
                with self.server.lock:
                    current = self.server.runs.get(run_id)
                    event = self.server.cancellations.get(run_id)
                    if current is None:
                        return self._json(404, {"error": "unknown run"})
                    if current["state"] not in {"running", "cancelling"} or event is None:
                        return self._json(409, {"error": "run has already finished", "state": current["state"]})
                    event.set()
                    current["state"] = "cancelling"
                return self._json(202, {"runId": run_id, "state": "cancelling"})
            if path.startswith("/api/run/"):
                name = unquote(path.removeprefix("/api/run/"))
                workflow = load_workflow(workflow_file(self.server.workflows, name))
                approve = body.get("approve") is True
                if workflow.get("permissions", "write") == "write" and not approve:
                    raise WorkflowError("write workflow requires approve:true")
                inputs = body.get("inputs", {})
                validate_inputs(workflow, inputs)
                if not self.server.execution_slots.acquire(blocking=False):
                    return self._json(429, {"error": "two workflows are already running; try after one finishes"})
                run_id = secrets.token_hex(12)
                stop_event = threading.Event()
                started_at = int(time.time())
                try:
                    self.server.journal.start(run_id, name, workflow.get("target", "browser"), len(workflow["steps"]))
                    with self.server.lock:
                        self.server.cancellations[run_id] = stop_event
                        self.server.runs[run_id] = {"state": "running", "workflow": name, "createdAt": started_at, "lastStep": None}
                except Exception:
                    self.server.execution_slots.release()
                    raise
                def track_step(index: int, action: str, state: str) -> None:
                    # Persist only action name, ordinal and status in memory. Never input values.
                    with self.server.lock:
                        if run_id in self.server.runs:
                            self.server.runs[run_id]["lastStep"] = {"index": index, "action": action, "state": state}
                def task() -> None:
                    started_ns = time.monotonic_ns()
                    try:
                        result = run_workflow(workflow, inputs, approve_writes=approve,
                            artifacts_dir=self.server.workflows.parent / "runs",
                            heal_selectors=body.get("healSelectors") is True or body.get("aiHeal") is True,
                            ai_heal=body.get("aiHeal") is True, run_id=run_id,
                            cancel_event=stop_event, on_step=track_step)
                        status = {"state": "completed", "result": result}
                    except RunCancelled:
                        status = {"state": "cancelled", "error": "execution cancelled by user"}
                    except (WorkflowError, ValueError, OSError) as exc:
                        status = {"state": "cancelled" if stop_event.is_set() else "failed", "error": str(exc)[:600]}
                    except Exception as exc:
                        status = {"state": "failed", "error": f"Unexpected engine error ({type(exc).__name__})"}
                    finally:
                        self.server.execution_slots.release()
                    try:
                        self.server.journal.finish(run_id, status["state"], (time.monotonic_ns() - started_ns) // 1_000_000)
                    except sqlite3.Error:
                        pass
                    with self.server.lock:
                        previous = self.server.runs.get(run_id, {})
                        self.server.runs[run_id] = {**status, "lastStep": previous.get("lastStep"), "workflow": name, "createdAt": started_at, "finishedAt": int(time.time())}
                        self.server.cancellations.pop(run_id, None)
                        self.server.purge_results()
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
                launcher = [sys.executable, "--h2a-cli"] if getattr(sys, "frozen", False) else [sys.executable, "-m", "human2api"]
                cmd = launcher + ["record", url, "--name", name, "--directory", str(self.server.workflows)]
                self.server.recorder = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return self._json(202, {"started": True, "message": "Use Stop & save in the new Chromium window"})
            return self._json(404, {"error": "not found"})
        except (WorkflowError, ValueError, OSError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)[:300]})


def make_server(workflows: Path, port: int = 8765) -> Human2APIServer:
    workflows.mkdir(parents=True, exist_ok=True)
    return Human2APIServer(("127.0.0.1", port), workflows)
