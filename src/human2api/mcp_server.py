"""Small MCP stdio adapter. No account, external API, or AI model required.

Implements the tools and initialization portions of JSON-RPC MCP v2025-11-25.
One workflow becomes one typed MCP tool. Python stdout is reserved for JSON-RPC.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .models import WorkflowError, input_json_schema, list_workflows, load_workflow, workflow_file
from .runner import run_workflow


def mcp_tools(directory: Path) -> list[dict[str, Any]]:
    result = [{
        "name": "h2a_list_workflows",
        "description": "List browser automations installed in this local Human2API instance.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": True},
    }]
    for entry in list_workflows(directory):
        workflow = load_workflow(workflow_file(directory, entry["name"]))
        result.append({
            "name": "h2a_" + entry["name"],
            "description": workflow["description"] + " (Human2API local browser automation)",
            "inputSchema": input_json_schema(workflow),
            "annotations": {
                "readOnlyHint": workflow.get("permissions") == "read",
                "destructiveHint": workflow.get("permissions", "write") == "write",
                "openWorldHint": True,
            },
        })
    return result


def _tool_call(directory: Path, name: str, args: dict[str, Any]) -> dict[str, Any]:
    try:
        if name == "h2a_list_workflows":
            result = list_workflows(directory)
        elif name.startswith("h2a_"):
            workflow = load_workflow(workflow_file(directory, name[4:]))
            write_ok = os.environ.get("H2A_ALLOW_WRITE", "0").lower() in {"1", "true", "yes"}
            result = run_workflow(workflow, args, approve_writes=write_ok, artifacts_dir=directory.parent / "runs")
        else:
            raise WorkflowError(f"unknown MCP tool: {name}")
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}], "isError": False}
    except (WorkflowError, FileNotFoundError, OSError) as exc:
        return {"content": [{"type": "text", "text": str(exc)[:600]}], "isError": True}


def handle_message(request: dict[str, Any], directory: Path) -> dict[str, Any] | None:
    method = request.get("method")
    id_ = request.get("id")
    if id_ is None:
        return None  # Notifications never receive a response.
    params = request.get("params") or {}
    try:
        if method == "initialize":
            result = {
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "human2api", "version": __version__},
                "instructions": "Human2API tools operate a local Chromium browser. Tools marked write require H2A_ALLOW_WRITE=1 and authorization from the user. No form values are saved in workflows.",
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": mcp_tools(directory)}
        elif method == "tools/call":
            result = _tool_call(directory, params.get("name", ""), params.get("arguments") or {})
        elif method == "resources/list":
            result = {"resources": []}
        elif method == "prompts/list":
            result = {"prompts": []}
        else:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32601, "message": "Method not found"}}
        return {"jsonrpc": "2.0", "id": id_, "result": result}
    except (WorkflowError, TypeError, ValueError, OSError) as exc:
        return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32602, "message": str(exc)[:300]}}


def serve_mcp(directory: Path) -> None:
    """Reads exactly one JSON-RPC object per line from stdin."""
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("request must be a JSON object")
            response = handle_message(request, directory)
        except (ValueError, json.JSONDecodeError):
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        if response is not None:
            print(json.dumps(response, separators=(",", ":"), ensure_ascii=False), flush=True)
