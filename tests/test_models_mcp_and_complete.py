"""Comprehensive Unit, Integration, MCP Protocol, Scheduler, History, Batch, Load/Soak, and Schema Compatibility Tests."""

from __future__ import annotations

import pathlib
import tempfile
import time
import unittest

from human2api.batch import run_soak_test, run_workflow_batch
from human2api.cli import main as cli_main
from human2api.desktop import WindowsUIAAdapter
from human2api.desktop_access import DesktopAccessibleNode
from human2api.editor import VisualWorkflowEditor
from human2api.mcp_server import MCPServer
from human2api.models import (
    SUPPORTED_ACTIONS,
    SUPPORTED_TARGETS,
    InputSpec,
    Workflow,
    WorkflowStep,
)
from human2api.runner import WorkflowRunner
from human2api.workspace import Workspace


class TestModelsMCPAndProtocol(unittest.TestCase):
    def test_legacy_workflow_migration_01_to_05(self) -> None:
        for legacy_ver in ("0.1", "0.2", "0.3", "0.4"):
            raw = {
                "schemaVersion": legacy_ver,
                "name": f"Legacy {legacy_ver} Workflow",
                "platform": "browser",
                "requiresWrite": True,
                "steps": [
                    {"type": "goto", "url": "http://127.0.0.2/demo"},
                    {"type": "input", "selector": "#name", "text": "{{username}}"},
                ],
            }
            wf = Workflow.from_dict(raw)
            self.assertEqual(wf.target, "browser")
            self.assertEqual(wf.mode, "write")
            self.assertEqual(wf.steps[1].action, "type")
            self.assertEqual(wf.steps[1].text, "${input:username}")

    def test_all_supported_targets_and_actions_validation(self) -> None:
        for tgt in SUPPORTED_TARGETS:
            wf = Workflow(
                name=f"Target {tgt}",
                target=tgt,
                steps=[WorkflowStep(action="wait", timeoutMs=100)],
            )
            self.assertEqual(wf.target, tgt)
        for act in SUPPORTED_ACTIONS:
            st = WorkflowStep.from_dict({"action": act, "url": "http://127.0.0.2/demo", "selector": "#x"})
            self.assertEqual(st.action, act)

    def test_mcp_protocol_initialize_list_and_write_approval_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(pathlib.Path(tmp))
            ws.initialize()
            node = DesktopAccessibleNode(
                node_id="n1",
                automation_id="btn1",
                name="RunBtn",
                role="button",
                window_title="App",
                app_name="App",
            )
            adapter = WindowsUIAAdapter([node])
            runner = WorkflowRunner(vault=ws.vault, workspace_dir=ws.root_dir, desktop_adapter=adapter)
            mcp = MCPServer(workspace=ws, runner=runner)

            wf = Workflow(
                name="Approve Write Task",
                target="windows-uia",
                mode="write",
                allowedApps=["App"],
                inputs={"user": InputSpec(type="string", default="Karem")},
                steps=[WorkflowStep(action="click", selector='automationId="btn1"', role="button", isWriteAction=True)],
            )
            mcp.register_workflow(wf)

            init_resp = mcp.handle_rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
            self.assertIn("protocolVersion", init_resp["result"])

            list_resp = mcp.handle_rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            tools = list_resp["result"]["tools"]
            self.assertEqual(len(tools), 1)
            self.assertEqual(tools[0]["name"], "h2a_approve_write_task")
            self.assertTrue(tools[0]["annotations"]["requiresWriteApproval"])

            call_denied = mcp.handle_rpc(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "h2a_approve_write_task", "arguments": {"user": "Karem"}, "allowWrite": False},
                }
            )
            self.assertTrue(call_denied["result"]["isError"])
            self.assertIn("write approval", call_denied["result"]["report"]["error"])

            call_ok = mcp.handle_rpc(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {"name": "h2a_approve_write_task", "arguments": {"user": "Karem"}, "allowWrite": True},
                }
            )
            self.assertFalse(call_ok["result"]["isError"])
            self.assertEqual(call_ok["result"]["report"]["status"], "passed")

    def test_visual_editor_operations_scheduler_history_and_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(pathlib.Path(tmp))
            ws.initialize()
            wf = Workflow(
                name="Editable Task",
                target="windows-uia",
                steps=[WorkflowStep(action="focus_window", windowTitle="App")],
            )
            wf = VisualWorkflowEditor.add_step(wf, {"action": "click", "selector": 'automationId="btn1"', "role": "button"})
            self.assertEqual(len(wf.steps), 2)
            wf = VisualWorkflowEditor.reorder_steps(wf, 0, 1)
            self.assertEqual(wf.steps[0].action, "click")
            wf = VisualWorkflowEditor.set_input_parameter(wf, "token", input_type="secret", sensitive=True, default="ShouldBeDropped")
            self.assertIsNone(wf.inputs["token"].default)
            wf = VisualWorkflowEditor.delete_step(wf, 0)
            self.assertEqual(len(wf.steps), 1)

            executed_jobs = []
            ws.scheduler.executor = lambda job: (executed_jobs.append(job.job_id) or "passed")
            job = ws.scheduler.add_job("workflows/t.json", "Editable Task", interval_seconds=5)
            ws.scheduler.tick(now=time.time() + 10.0)
            self.assertEqual(len(executed_jobs), 1)
            ws.scheduler.set_enabled(job.job_id, False)
            self.assertTrue(ws.scheduler.remove_job(job.job_id))

            node = DesktopAccessibleNode(
                node_id="n1",
                automation_id="edit1",
                name="Edit",
                role="textbox",
                window_title="App",
                app_name="App",
            )
            adapter = WindowsUIAAdapter([node])
            runner = WorkflowRunner(desktop_adapter=adapter)
            batch_wf = Workflow(
                name="Batch Task",
                target="windows-uia",
                mode="write",
                allowedApps=["App"],
                inputs={"val": InputSpec(type="string")},
                steps=[WorkflowStep(action="type", selector='automationId="edit1"', text="${input:val}", role="textbox", isWriteAction=True)],
            )
            reports = run_workflow_batch(runner, batch_wf, [{"val": "Row1"}, {"val": "Row2"}], allow_write=True)
            self.assertEqual(len(reports), 2)
            self.assertTrue(all(r.status == "passed" for r in reports))

    def test_soak_and_cli_commands(self) -> None:
        soak_res = run_soak_test(num_requests=24, concurrency=4)
        self.assertEqual(soak_res["errors"], 0)
        self.assertEqual(soak_res["requests_succeeded"], 24)
        self.assertTrue(soak_res["callback_invoked"])

        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(cli_main(["init", "--dir", tmp]), 0)
            out_wf = pathlib.Path(tmp) / "rec.json"
            self.assertEqual(cli_main(["record", "--name", "CLI Test", "--output", str(out_wf)]), 0)
            self.assertTrue(out_wf.exists())


if __name__ == "__main__":
    unittest.main()
