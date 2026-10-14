"""Model Context Protocol (MCP) JSON-RPC 2.0 Server for exposing Human2API workflows as AI agent tools."""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, List, Optional

from human2api import __version__
from human2api.contracts import redact_secrets
from human2api.execution import CancellationToken
from human2api.models import Workflow
from human2api.runner import WorkflowRunner
from human2api.workspace import Workspace


class MCPServer:
    """Implements MCP JSON-RPC 2.0 protocol (`initialize`, `tools/list`, `tools/call`, `ping`) with write-approval gates."""

    PROTOCOL_VERSION = "2024-11-05"

    def __init__(
        self,
        workspace: Workspace,
        runner: Optional[WorkflowRunner] = None,
        workflows: Optional[Dict[str, Workflow]] = None,
    ) -> None:
        self.workspace = workspace
        self.runner = runner or WorkflowRunner(vault=workspace.vault, workspace_dir=workspace.root_dir)
        self._workflows: Dict[str, Workflow] = dict(workflows or {})

    def register_workflow(self, workflow: Workflow) -> None:
        key = self._tool_name(workflow.name)
        self._workflows[key] = workflow

    @staticmethod
    def _tool_name(name: str) -> str:
        import re

        cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", name.strip()).strip("_").lower()
        return f"h2a_{cleaned or 'workflow'}"

    def _discover_workflows(self) -> Dict[str, Workflow]:
        merged = dict(self._workflows)
        for wf_dict in self.workspace.list_workflows():
            wf = Workflow.from_dict(wf_dict)
            merged[self._tool_name(wf.name)] = wf
        return merged

    def list_tools(self) -> List[Dict[str, Any]]:
        tools: List[Dict[str, Any]] = []
        for tool_name, wf in sorted(self._discover_workflows().items()):
            props: Dict[str, Any] = {}
            req: List[str] = []
            for inp_name, spec in wf.inputs.items():
                json_type = "string"
                if spec.type in ("number", "integer", "boolean"):
                    json_type = spec.type
                props[inp_name] = {
                    "type": json_type,
                    "description": spec.description or f"Parameter {inp_name}",
                }
                if spec.required and spec.default is None:
                    req.append(inp_name)
            tools.append(
                {
                    "name": tool_name,
                    "description": wf.description or f"Execute Human2API {wf.target} workflow: {wf.name}",
                    "inputSchema": {
                        "type": "object",
                        "properties": props,
                        "required": req,
                        "additionalProperties": False,
                    },
                    "annotations": {
                        "target": wf.target,
                        "mode": wf.mode,
                        "requiresWriteApproval": wf.requires_write_approval(),
                    },
                }
            )
        return tools

    def handle_rpc(self, request: Dict[str, Any]) -> Dict[str, Any]:
        req_id = request.get("id")
        if request.get("jsonrpc") != "2.0" or "method" not in request:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32600, "message": "Invalid JSON-RPC 2.0 request."},
            }

        method = str(request["method"])
        params = request.get("params") or {}

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": self.PROTOCOL_VERSION,
                    "serverInfo": {"name": "human2api-mcp", "version": __version__},
                    "capabilities": {"tools": {"listChanged": True}},
                },
            }

        if method in ("notifications/initialized", "initialized"):
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}

        if method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"status": "pong"}}

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": self.list_tools()},
            }

        if method == "tools/call":
            tool_name = str(params.get("name") or "")
            arguments = dict(params.get("arguments") or {})
            allow_write = bool(params.get("allowWrite", False) or arguments.pop("_allowWrite", False))
            catalog = self._discover_workflows()
            if tool_name not in catalog:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": f"Unknown MCP tool: {tool_name!r}"},
                }
            wf = catalog[tool_name]
            report = self.runner.run(
                workflow=wf,
                inputs=arguments,
                allow_write=allow_write,
                cancel_token=CancellationToken(),
            )
            secrets_set = self.workspace.vault.all_secret_values() if self.workspace.vault.is_unlocked() else set()
            rep_dict = report.to_dict(secret_values=secrets_set)
            is_err = report.status != "passed"
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "isError": is_err,
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(rep_dict, ensure_ascii=False),
                        }
                    ],
                    "report": rep_dict,
                },
            }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method!r}"},
        }

    def serve_stdio(self) -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
                resp = self.handle_rpc(req)
            except Exception as exc:
                resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": redact_secrets(str(exc))},
                }
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
