"""Dual-era MCP stdio: 2026-07-28 metadata and legacy initialization.

Only documented tools are exposed. Bounded workers allow cancellation while a
workflow executes. No input values or non-protocol text are written to stdout.
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .models import WorkflowError, input_json_schema, list_workflows, load_workflow, workflow_file
from .runner import run_workflow

MODERN = "2026-07-28"
LEGACY = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
VERSION_KEY = "io.modelcontextprotocol/protocolVersion"
CAPABILITIES_KEY = "io.modelcontextprotocol/clientCapabilities"
MAX_MESSAGE = 1024 * 1024
INFO = {"name": "human2api", "version": __version__}
INSTRUCTIONS = "Local browser, desktop and Android workflows. Writes require H2A_ALLOW_WRITE=1 AND the user's authorization in your MCP client. Never blindly retry mutations. Native cancellation is cooperative. AI recovery transmits bounded UI metadata only when explicitly enabled."


def error(id_: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    value: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        value["data"] = data
    return {"jsonrpc": "2.0", "id": id_, "error": value}


def mcp_tools(directory: Path) -> list[dict[str, Any]]:
    result = [{"name": "h2a_list_workflows", "description": "List installed local browser, desktop and Android automations.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "idempotentHint": True}}]
    for entry in list_workflows(directory):
        workflow = load_workflow(workflow_file(directory, entry["name"]))
        result.append({"name": "h2a_" + entry["name"], "description": workflow["description"] + f" (local {workflow.get('target', 'browser')} automation)",
            "inputSchema": input_json_schema(workflow), "annotations": {"readOnlyHint": workflow.get("permissions") == "read",
            "destructiveHint": workflow.get("permissions", "write") == "write", "idempotentHint": False, "openWorldHint": True}})
    return result


def _tool_call(directory: Path, name: str, args: dict[str, Any], *, cancel_event: threading.Event | None = None,
               on_step: Callable | None = None) -> dict[str, Any]:
    try:
        if not isinstance(name, str) or not isinstance(args, dict):
            raise WorkflowError("tool name must be a string and arguments an object")
        if name == "h2a_list_workflows":
            if args:
                raise WorkflowError("list_workflows does not accept arguments")
            result = list_workflows(directory)
        elif name.startswith("h2a_"):
            workflow = load_workflow(workflow_file(directory, name[4:]))
            write_ok = os.environ.get("H2A_ALLOW_WRITE", "0").lower() in {"1", "true", "yes"}
            result = run_workflow(workflow, args, approve_writes=write_ok, artifacts_dir=directory.parent / "runs",
                heal_selectors=os.environ.get("H2A_HEAL_SELECTORS") == "1", ai_heal=os.environ.get("H2A_AI_HEAL") == "1",
                cancel_event=cancel_event, on_step=on_step)
        else:
            raise WorkflowError("unknown MCP tool")
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}], "isError": False}
    except (WorkflowError, OSError) as exc:
        return {"content": [{"type": "text", "text": str(exc)[:600]}], "isError": True}


def handle_message(request: dict[str, Any], directory: Path, *, cancel_event: threading.Event | None = None,
                   on_step: Callable | None = None) -> dict[str, Any] | None:
    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str):
        return error(None, -32600, "Invalid Request")
    if "id" not in request:
        return None
    id_ = request["id"]
    if type(id_) not in (str, int):
        return error(None, -32600, "Request ID must be a string or integer")
    method = request["method"]
    params = request.get("params", {})
    if not isinstance(params, dict) or not isinstance(params.get("_meta", {}), dict):
        return error(id_, -32602, "Params and _meta must be objects")
    meta = params.get("_meta", {})
    modern = VERSION_KEY in meta or method == "server/discover"
    if modern:
        if not isinstance(meta.get(VERSION_KEY), str) or not isinstance(meta.get(CAPABILITIES_KEY), dict):
            return error(id_, -32602, "Modern requests require protocolVersion and clientCapabilities in _meta")
        if "io.modelcontextprotocol/clientInfo" in meta:
            info = meta["io.modelcontextprotocol/clientInfo"]
            if not isinstance(info, dict) or not all(isinstance(info.get(key), str) and info[key] for key in ("name", "version")):
                return error(id_, -32602, "clientInfo requires nonempty name and version strings")
        if meta[VERSION_KEY] != MODERN:
            return error(id_, -32022, "Unsupported protocol version", {"supported": [MODERN, *LEGACY], "requested": meta[VERSION_KEY]})
    try:
        if method == "initialize":
            if modern:
                return error(id_, -32601, "Modern requests do not use initialize")
            requested = params.get("protocolVersion")
            result = {"protocolVersion": requested if requested in LEGACY else LEGACY[0],
                "capabilities": {"tools": {"listChanged": False}}, "serverInfo": INFO, "instructions": INSTRUCTIONS}
        elif method == "server/discover":
            result = {"supportedVersions": [MODERN, *LEGACY], "capabilities": {"tools": {"listChanged": False}}, "instructions": INSTRUCTIONS}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            tools = mcp_tools(directory)
            digest = hashlib.sha256(json.dumps(tools, sort_keys=True).encode()).hexdigest()[:16]
            offset = 0
            if "cursor" in params:
                cursor = params["cursor"]
                if not isinstance(cursor, str) or len(cursor) > 100:
                    raise WorkflowError("invalid cursor")
                offset, signature = json.loads(base64.urlsafe_b64decode(cursor))
                if type(offset) is not int or not 0 <= offset < len(tools) or signature != digest:
                    raise WorkflowError("invalid or stale cursor")
            result = {"tools": tools[offset:offset+50]}
            if offset+50 < len(tools):
                result["nextCursor"] = base64.urlsafe_b64encode(json.dumps([offset+50, digest]).encode()).decode()
        elif method == "tools/call":
            result = _tool_call(directory, params.get("name", ""), params.get("arguments", {}), cancel_event=cancel_event, on_step=on_step)
        elif method == "resources/list":
            result = {"resources": []}
        elif method == "prompts/list":
            result = {"prompts": []}
        else:
            return error(id_, -32601, "Method not found")
        if modern:
            result = {**result, "resultType": "complete", "_meta": {"io.modelcontextprotocol/serverInfo": INFO}}
        return {"jsonrpc": "2.0", "id": id_, "result": result}
    except (WorkflowError, TypeError, ValueError, OSError, KeyError):
        return error(id_, -32602, "Invalid params or unavailable local workflow")


class StdioSession:
    """One transport with independent bounded operations; no chat-session state."""
    def __init__(self, directory: Path, emit: Callable[[dict], None]):
        self.directory, self.emit = directory, emit
        self.lock = threading.RLock()
        self.running: dict[Any, tuple[threading.Event, threading.Thread]] = {}
        self.initialized = False

    def send(self, message: dict, event: threading.Event | None = None) -> None:
        with self.lock:
            if event is None or not event.is_set():
                self.emit(message)

    def feed(self, request: Any) -> None:
        if not isinstance(request, dict):
            return self.send(error(None, -32600, "Requests must be objects; batches are not supported"))
        method, id_ = request.get("method"), request.get("id")
        params = request.get("params", {})
        if method == "notifications/cancelled" and "id" not in request:
            target = params.get("requestId") if isinstance(params, dict) else None
            if type(target) in (int, str):
                with self.lock:
                    active = self.running.get(target)
                    if active:
                        active[0].set()
            return
        meta = params.get("_meta", {}) if isinstance(params, dict) else {}
        modern = isinstance(meta, dict) and VERSION_KEY in meta
        if "id" in request and not modern and not self.initialized and method not in {"initialize", "ping", "server/discover"}:
            return self.send(error(id_ if type(id_) in (str,int) else None, -32600, "Initialize the legacy connection before operations"))
        if method != "tools/call" or type(id_) not in (str, int):
            response = handle_message(request, self.directory)
            if method == "initialize" and response and "result" in response:
                self.initialized = True
            if response is not None:
                self.send(response)
            return
        with self.lock:
            if id_ in self.running:
                return self.send(error(id_, -32600, "Duplicate in-flight request ID"))
            if len(self.running) >= 2:
                return self.send(error(id_, -32603, "Local execution capacity reached; no actions started"))
            event = threading.Event()
            progress_token = meta.get("progressToken") if isinstance(meta, dict) else None
            counter = [0]
            def progress(index: int, action: str, state: str) -> None:
                if type(progress_token) not in (int, str) or state != "passed":
                    return
                counter[0] += 1
                self.send({"jsonrpc":"2.0", "method":"notifications/progress", "params":{
                    "progressToken":progress_token, "progress":counter[0], "message":f"Step {index} ({action}) passed"}}, event)
            def work() -> None:
                try:
                    response = handle_message(request, self.directory, cancel_event=event, on_step=progress)
                    if response is not None:
                        self.send(response, event)
                except Exception:
                    self.send(error(id_, -32603, "Local execution failed; inspect the target before retrying"), event)
                finally:
                    with self.lock:
                        self.running.pop(id_, None)
            thread = threading.Thread(target=work, name="h2a-mcp-operation")
            self.running[id_] = (event, thread)
            thread.start()

    def close(self) -> None:
        with self.lock:
            active = list(self.running.values())
            for event, _ in active:
                event.set()
        for _, thread in active:
            thread.join()  # Cooperative: an in-flight native call may finish first.


def serve_mcp(directory: Path) -> None:
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="strict")
    def emit(value: dict) -> None:
        print(json.dumps(value, separators=(",", ":"), ensure_ascii=False), flush=True)
    session = StdioSession(directory, emit)
    try:
        while True:
            line = sys.stdin.readline(MAX_MESSAGE+1)
            if not line:
                break
            if len(line.encode("utf-8")) > MAX_MESSAGE:
                session.send(error(None, -32600, "Message exceeds 1 MiB; closing transport"))
                break
            if not line.strip():
                continue
            try:
                def reject_constant(value):
                    raise ValueError("non-JSON constant")
                request = json.loads(line, parse_constant=reject_constant)
            except ValueError:
                session.send(error(None, -32700, "Parse error"))
                continue
            session.feed(request)
    finally:
        session.close()
