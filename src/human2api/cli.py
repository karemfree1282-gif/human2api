"""Command-Line Interface (`h2a`) for Human2API."""

from __future__ import annotations

import argparse
import json
import pathlib
import platform
import sys
from typing import List, Optional

from human2api import __version__
from human2api.completion import check_dependencies_and_toolchains, run_complete_orchestrator
from human2api.desktop_access import detect_linux_display_protocol
from human2api.execution import CancellationToken
from human2api.http_server import Human2APIServer
from human2api.mcp_server import MCPServer
from human2api.models import Workflow
from human2api.recorder import WorkflowRecorder
from human2api.runner import WorkflowRunner
from human2api.trust import build_package_zip_bytes, generate_ed25519_keypair
from human2api.workspace import Workspace


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="h2a",
        description="Human2API — Record browser, desktop, and Android tasks. Reuse via CLI, REST API, MCP, and Visual Studio.",
    )
    parser.add_argument("--version", action="version", version=f"human2api {__version__}")
    sub = parser.add_subparsers(dest="command")

    # init
    p_init = sub.add_parser("init", help="Initialize a Human2API workspace in the current directory.")
    p_init.add_argument("--dir", default=".", help="Target workspace directory.")

    # doctor
    p_doc = sub.add_parser("doctor", help="Inspect runtime environment, browser, desktop, and Android capabilities.")
    p_doc.add_argument("--json", action="store_true", help="Output diagnostics as JSON.")

    # record
    p_rec = sub.add_parser("record", help="Compile recorded events or start a workflow recording session.")
    p_rec.add_argument("--name", default="Recorded Task", help="Workflow name.")
    p_rec.add_argument("--target", default="browser", help="Target engine (browser, windows-uia, macos-ax, linux-atspi, android-companion).")
    p_rec.add_argument("--events-file", help="Optional JSON file of recorded interaction events.")
    p_rec.add_argument("--output", required=True, help="Output workflow JSON path.")

    # run
    p_run = sub.add_parser("run", help="Execute a recorded workflow.")
    p_run.add_argument("--workflow", required=True, help="Path to workflow JSON file.")
    p_run.add_argument("--input", action="append", default=[], help="Input key=value override.")
    p_run.add_argument("--allow-write", action="store_true", help="Approve write/mutating actions.")

    # serve
    p_srv = sub.add_parser("serve", help="Start the local loopback REST API and Visual Studio server.")
    p_srv.add_argument("--host", default="127.0.0.1", help="Loopback bind address (127.0.0.1 or 127.0.0.2).")
    p_srv.add_argument("--port", type=int, default=8000, help="Port number.")

    # mcp
    sub.add_parser("mcp", help="Run the JSON-RPC 2.0 MCP server over stdio.")

    # keygen
    sub.add_parser("keygen", help="Generate an Ed25519 publisher keypair for signing Marketplace packages.")

    # publish
    p_pub = sub.add_parser("publish", help="Sign and package a workflow into a verified .h2apkg bundle.")
    p_pub.add_argument("--workflow", required=True, help="Path to workflow JSON.")
    p_pub.add_argument("--tool-id", required=True, help="Marketplace tool identifier.")
    p_pub.add_argument("--version", default="1.0.0", help="Semantic version.")
    p_pub.add_argument("--publisher-id", required=True, help="Publisher identifier.")
    p_pub.add_argument("--sign-key", required=True, help="Base64 Ed25519 private key.")
    p_pub.add_argument("--output", required=True, help="Output .h2apkg file path.")

    # complete
    p_cmp = sub.add_parser("complete", help="Run full engineering verification, test suite, package builds, and report generation.")
    p_cmp.add_argument("--repair", action="store_true", help="Regenerate deterministic schema/examples before checking.")
    p_cmp.add_argument("--evidence-dir", default=None, help="Output directory for JSON and HTML verification reports.")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    if args.command == "init":
        ws = Workspace(pathlib.Path(args.dir))
        info = ws.initialize()
        print(json.dumps({"status": "initialized", "workspace": info}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "doctor":
        checks = [c.to_dict() for c in check_dependencies_and_toolchains()]
        payload = {
            "version": __version__,
            "platform": platform.platform(),
            "linux_display": detect_linux_display_protocol(),
            "checks": checks,
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"Human2API v{__version__} Doctor ({payload['platform']})")
            for c in checks:
                print(f"  [{c['status'].upper()}] {c['name']}: {c['details']}")
        return 0

    if args.command == "record":
        rec = WorkflowRecorder(name=args.name, target=args.target)
        if args.events_file:
            evs = json.loads(pathlib.Path(args.events_file).read_text(encoding="utf-8"))
            for e in evs:
                rec.record_event(e)
        else:
            rec.record_event({"action": "goto", "url": "http://127.0.0.2:8000/demo"})
        wf = rec.compile_workflow()
        out_p = wf.save(args.output)
        print(json.dumps({"status": "recorded", "output": str(out_p)}, ensure_ascii=False))
        return 0

    if args.command == "run":
        ws = Workspace()
        wf = Workflow.load(args.workflow)
        inputs = {}
        for item in args.input:
            if "=" in item:
                k, v = item.split("=", 1)
                inputs[k.strip()] = v.strip()
        runner = WorkflowRunner(vault=ws.vault, workspace_dir=ws.root_dir)
        rep = runner.run(wf, inputs=inputs, allow_write=args.allow_write, cancel_token=CancellationToken())
        ws.history.record_run(rep)
        print(json.dumps(rep.to_dict(), ensure_ascii=False, indent=2))
        return 0 if rep.status == "passed" else 1

    if args.command == "serve":
        ws = Workspace()
        srv = Human2APIServer(workspace=ws, host=args.host, port=args.port)
        url = srv.start()
        print(f"Human2API Studio & REST Server listening on {url} (Token: {srv.auth_token})")
        try:
            import time

            while True:
                time.sleep(1.0)
        except KeyboardInterrupt:
            srv.stop()
        return 0

    if args.command == "mcp":
        ws = Workspace()
        mcp = MCPServer(workspace=ws)
        mcp.serve_stdio()
        return 0

    if args.command == "keygen":
        priv, pub = generate_ed25519_keypair()
        print(json.dumps({"private_key": priv, "public_key": pub}, indent=2))
        return 0

    if args.command == "publish":
        wf = Workflow.load(args.workflow)
        zip_bytes = build_package_zip_bytes(
            workflow=wf,
            private_key_b64=args.sign_key,
            tool_id=args.tool_id,
            version=args.version,
            publisher_id=args.publisher_id,
        )
        out = pathlib.Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(zip_bytes)
        print(json.dumps({"status": "packaged", "output": str(out), "size_bytes": len(zip_bytes)}))
        return 0

    if args.command == "complete":
        root = pathlib.Path(__file__).resolve().parents[2]
        out_dir = pathlib.Path(args.evidence_dir) if args.evidence_dir else None
        code, report = run_complete_orchestrator(root, repair=args.repair, output_dir=out_dir)
        print(
            json.dumps(
                {
                    "version": report["version"],
                    "summary": report["summary"],
                    "test_summary": report["test_summary"],
                    "built_artifacts": [a["name"] for a in report["built_artifacts"]],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return code

    return 0


if __name__ == "__main__":
    sys.exit(main())
