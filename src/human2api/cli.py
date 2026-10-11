"""CLI: record -> validate -> run -> serve/mcp/openapi."""

from __future__ import annotations

import argparse
import json
import os
import sys
import webbrowser
from pathlib import Path

from . import __version__
from .http_server import make_server, openapi_schema
from .mcp_server import serve_mcp
from .models import WorkflowError, list_workflows, load_workflow, workflow_file
from .recorder import record
from .runner import run_workflow
from .marketplace import pack_workflow, inspect_package, install_package, local_catalog


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="h2a", description="Human2API: record once, automate everywhere")
    parser.add_argument("--version", action="version", version=f"h2a {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("record", help="Capture a real browser session; inputs become named variables")
    p.add_argument("url", help="Starting HTTP(S) page URL")
    p.add_argument("--name", required=True, help="Machine-readable name, e.g. create_invoice")
    p.add_argument("--directory", type=Path, default=Path("workflows"))
    p.add_argument("--browser-path", default=None)
    p.add_argument("--headless", action="store_true", help="For automated tests only; no visible Stop button")

    p = sub.add_parser("record-desktop", help="Record only desktop mouse clicks/scrolls (F12 to stop); NEVER records typed text")
    p.add_argument("--name", required=True)
    p.add_argument("--directory", type=Path, default=Path("workflows"))
    p = sub.add_parser("record-android", help="Interactively teach an authorized Android device with ADB")
    p.add_argument("--name", required=True)
    p.add_argument("--serial", help="Explicit authorized Android device ID")
    p.add_argument("--directory", type=Path, default=Path("workflows"))
    p = sub.add_parser("devices", help="List authorized Android ADB devices")
    p.add_argument("--directory", type=Path, default=Path("workflows"))
    p = sub.add_parser("pack", help="Create a checksummed .h2a.zip package containing a reviewed workflow")
    p.add_argument("name")
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--publisher", default="community")
    p.add_argument("--directory", type=Path, default=Path("workflows"))
    p = sub.add_parser("verify", help="Verify a local .h2a.zip package before installation")
    p.add_argument("package", type=Path)
    p.add_argument("--directory", type=Path, default=Path("workflows"))
    p = sub.add_parser("install", help="Install a checksummed workflow package into local workflows")
    p.add_argument("package", type=Path)
    p.add_argument("--approve", action="store_true")
    p.add_argument("--directory", type=Path, default=Path("workflows"))
    p = sub.add_parser("catalog", help="List .h2a.zip packages in a local catalog directory")
    p.add_argument("--catalog-dir", type=Path, default=Path("catalog"))
    p.add_argument("--directory", type=Path, default=Path("workflows"))

    for cmd in ["list", "check", "run", "mcp", "serve", "openapi"]:
        p = sub.add_parser(cmd)
        p.add_argument("--directory", type=Path, default=Path("workflows"))
        if cmd in {"check", "run"}:
            p.add_argument("name", help="Filename without .json (or an explicit .json path)")
        if cmd == "run":
            p.add_argument("--data", default="{}", help="JSON object of workflow inputs")
            p.add_argument("--data-file", type=Path, help="Read JSON inputs from a file instead")
            p.add_argument("--approve", action="store_true", help="Explicitly approve write workflows")
            p.add_argument("--show-browser", action="store_true")
            p.add_argument("--browser-path", default=None)
            p.add_argument("--heal-selectors", action="store_true", help="Opt in to safe, local selector recovery")
            p.add_argument("--ai-heal", action="store_true", help="Explicitly permit sending sanitized UI metadata to your configured AI provider")
        if cmd == "serve":
            p.add_argument("--port", type=int, default=int(os.environ.get("H2A_PORT", "8765")))
            p.add_argument("--no-open", action="store_true", help="Do not open the local dashboard")
        if cmd == "openapi":
            p.add_argument("--port", type=int, default=8765)
            p.add_argument("--output", type=Path, help="Write the OpenAPI 3.1 document to disk")
    return parser


def _path(directory: Path, name: str) -> Path:
    if name.endswith(".json") or "/" in name or "\\" in name:
        return Path(name)
    return workflow_file(directory, name)


def main(argv: list[str] | None = None) -> int:
    args = create_parser().parse_args(argv)
    try:
        directory = args.directory
        if args.command == "record-desktop":
            from .desktop import record_desktop
            print("Saved:", record_desktop(args.name, directory))
        elif args.command == "record-android":
            from .android import record_android
            print("Saved:", record_android(args.name, directory, serial=args.serial))
        elif args.command == "devices":
            from .android import adb_devices
            print(json.dumps({"authorizedDevices": adb_devices()}, indent=2))
        elif args.command == "pack":
            print("Packed:", pack_workflow(_path(directory, args.name), args.output, publisher=args.publisher))
        elif args.command == "verify":
            manifest, _ = inspect_package(args.package)
            print(json.dumps({"verified": True, "manifest": manifest}, indent=2))
        elif args.command == "install":
            print("Installed:", install_package(args.package, directory, approve=args.approve))
        elif args.command == "catalog":
            print(json.dumps(local_catalog(args.catalog_dir), indent=2))
        elif args.command == "record":
            print("No form values or passwords are stored. Inspect the workflow before sharing it.", file=sys.stderr)
            path = record(args.url, name=args.name, output_dir=directory, browser_path=args.browser_path, headless=args.headless)
            print(f"Saved: {path}\nNext: h2a check {args.name}")
        elif args.command == "list":
            print(json.dumps(list_workflows(directory), indent=2))
        elif args.command == "check":
            wf = load_workflow(_path(directory, args.name))
            print(f"Valid: {wf['name']} | {len(wf['steps'])} steps | {len(wf.get('inputs', {}))} inputs")
        elif args.command == "run":
            raw = args.data_file.read_text(encoding="utf-8") if args.data_file else args.data
            inputs = json.loads(raw)
            wf = load_workflow(_path(directory, args.name))
            print(json.dumps(run_workflow(wf, inputs, approve_writes=args.approve, headless=not args.show_browser, browser_path=args.browser_path, heal_selectors=args.heal_selectors or args.ai_heal, ai_heal=args.ai_heal), indent=2))
        elif args.command == "mcp":
            serve_mcp(directory)
        elif args.command == "openapi":
            spec = json.dumps(openapi_schema(directory, port=args.port), indent=2)
            if args.output:
                args.output.write_text(spec + "\n", encoding="utf-8")
                print(f"Saved OpenAPI: {args.output}")
            else:
                print(spec)
        elif args.command == "serve":
            if not 0 <= args.port <= 65535:
                raise WorkflowError("port must be between 0 and 65535")
            server = make_server(directory, port=args.port)
            url = f"http://127.0.0.1:{server.server_address[1]}"
            print(f"Human2API dashboard: {url}")
            print("REST API token is intentionally ephemeral and embedded in the local dashboard.")
            if not args.no_open:
                webbrowser.open(url)
            try:
                server.serve_forever(poll_interval=0.2)
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
        return 0
    except (WorkflowError, OSError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
