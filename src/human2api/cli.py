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
from .marketplace import pack_workflow, inspect_package, install_package, local_catalog, remote_catalog, install_remote, DEFAULT_CATALOG_URL


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
    # Native accessibility enriches clicks and editable placeholders without typed content.
    sub.choices["record-desktop"].add_argument("--smart", action="store_true", help="Prefer stable native accessibility selectors for clicks")
    p = sub.add_parser("record-android", help="Interactively teach an authorized Android device with ADB")
    p.add_argument("--name", required=True)
    p.add_argument("--serial", help="Explicit authorized Android device ID")
    p.add_argument("--directory", type=Path, default=Path("workflows"))
    p = sub.add_parser("inspect-desktop", help="List non-secret native accessibility selectors in an approved window")
    p.add_argument("--window", required=True, help="Exact title of the permitted window")
    p.add_argument("--limit", type=int, default=60)
    p.add_argument("--directory", type=Path, default=Path("workflows"))
    p = sub.add_parser("keygen", help="Create a private/public Ed25519 package signing keypair")
    p.add_argument("--private", required=True, type=Path)
    p.add_argument("--public", required=True, type=Path)
    p.add_argument("--directory", type=Path, default=Path("workflows"))
    p = sub.add_parser("devices", help="List authorized Android ADB devices")
    p.add_argument("--directory", type=Path, default=Path("workflows"))
    p = sub.add_parser("pack", help="Create a checksummed .h2a.zip package containing a reviewed workflow")
    p.add_argument("name")
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--publisher", default="community")
    p.add_argument("--sign-key", type=Path, help="Ed25519 private key; creates a signed v2 package")
    p.add_argument("--release-version", help="Signed major.minor.patch version required for registry publishing")
    p.add_argument("--directory", type=Path, default=Path("workflows"))
    p = sub.add_parser("verify", help="Verify a local .h2a.zip package before installation")
    p.add_argument("package", type=Path)
    p.add_argument("--trust-key", type=Path, help="Pin the publisher public key for verification")
    p.add_argument("--directory", type=Path, default=Path("workflows"))
    p = sub.add_parser("install", help="Install a checksummed workflow package into local workflows")
    p.add_argument("package", type=Path)
    p.add_argument("--trust-key", type=Path, help="Reject packages not signed by this pinned public key")
    p.add_argument("--approve", action="store_true")
    p.add_argument("--directory", type=Path, default=Path("workflows"))
    p = sub.add_parser("catalog", help="List local catalog packages or a remote HTTPS registry")
    p.add_argument("--catalog-dir", type=Path, default=Path("catalog"))
    p.add_argument("--remote", action="store_true", help="Query the community JSON index")
    p.add_argument("--catalog-url", default=DEFAULT_CATALOG_URL, help="Remote catalog index HTTPS URL")
    p.add_argument("--directory", type=Path, default=Path("workflows"))

    p = sub.add_parser("install-remote", help="Download a SHA256-pinned JSON workflow from the community index (opt-in)")
    p.add_argument("name")
    p.add_argument("--approve", action="store_true")
    p.add_argument("--trust-key", type=Path)
    p.add_argument("--catalog-url", default=DEFAULT_CATALOG_URL)
    p.add_argument("--directory", type=Path, default=Path("workflows"))

    p = sub.add_parser("schedule", help="Manage local recurring automation schedules")
    p.add_argument("action", choices=["list", "add", "remove"])
    p.add_argument("name", nargs="?", help="Workflow name for add/remove")
    p.add_argument("--every-minutes", type=int, default=60)
    p.add_argument("--data-file", type=Path, help="Private JSON file; values never enter schedules.json")
    p.add_argument("--approve", action="store_true", help="Permit recurring write actions without an interactive prompt")
    p.add_argument("--directory", type=Path, default=Path("workflows"))
    p = sub.add_parser("scheduler", help="Run explicitly enabled local schedules; remains foreground")
    p.add_argument("--directory", type=Path, default=Path("workflows"))
    p.add_argument("--once", action="store_true")
    p.add_argument("--poll-seconds", type=int, default=10)

    for cmd in ["list", "check", "run", "plan", "history", "mcp", "serve", "openapi"]:
        p = sub.add_parser(cmd)
        p.add_argument("--directory", type=Path, default=Path("workflows"))
        if cmd in {"check", "run", "plan"}:
            p.add_argument("name", help="Filename without .json (or an explicit .json path)")
        if cmd in {"run", "plan"}:
            p.add_argument("--data", default="{}", help="JSON object of workflow inputs")
            p.add_argument("--data-file", type=Path, help="Read JSON inputs from a file instead")
            if cmd == "run":
                p.add_argument("--approve", action="store_true", help="Explicitly approve write workflows")
            if cmd == "run":
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
    p = sub.add_parser("init", help="Create packaged example workflows without overwriting files")
    p.add_argument("--directory", type=Path, default=Path("workflows"))
    p = sub.add_parser("studio", help="Open the native desktop studio (optional pywebview)")
    p.add_argument("--directory", type=Path, default=Path("workflows"))
    p = sub.add_parser("vault", help="Manage a password-encrypted local secret vault")
    p.add_argument("action", choices=["init", "set", "delete", "list"])
    p.add_argument("name", nargs="?")
    p.add_argument("--file", type=Path, default=Path(".h2a/secrets.vault"))
    p.add_argument("--directory", type=Path, default=Path("workflows"))
    p = sub.add_parser("batch", help="Run validated CSV/JSON/JSONL rows sequentially; stop on error")
    p.add_argument("name")
    p.add_argument("--file", type=Path, required=True)
    p.add_argument("--approve", action="store_true")
    p.add_argument("--directory", type=Path, default=Path("workflows"))
    sub.choices["run"].add_argument("--vault", type=Path, help="Encrypted secret vault path")
    sub.choices["run"].add_argument("--secret", action="append", default=[], metavar="INPUT=ENTRY", help="Resolve a declared secret input from the unlocked vault")
    p = sub.add_parser("registry", help="Run or administer the signed package registry")
    p.add_argument("registry_args", nargs=argparse.REMAINDER)
    p.add_argument("--directory", type=Path, default=Path("workflows"))
    p = sub.add_parser("registry-install", help="Install a signed package or perform a provenance-checked upgrade")
    p.add_argument("publisher")
    p.add_argument("name")
    p.add_argument("version")
    p.add_argument("--origin", required=True)
    p.add_argument("--trust-key", type=Path, required=True)
    p.add_argument("--approve", action="store_true")
    p.add_argument("--upgrade", action="store_true")
    p.add_argument("--directory", type=Path, default=Path("workflows"))
    p = sub.add_parser("complete", help="Repair generated files, test, build, and report release gates")
    p.add_argument("completion_args", nargs=argparse.REMAINDER)
    p.add_argument("--directory", type=Path, default=Path("workflows"))
    return parser


def _path(directory: Path, name: str) -> Path:
    if name.endswith(".json") or "/" in name or "\\" in name:
        return Path(name)
    return workflow_file(directory, name)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "complete":
        from .completion import main as complete_main
        return complete_main(argv[1:])
    args = create_parser().parse_args(argv)
    try:
        directory = args.directory
        if args.command == "registry":
            from .registry import main as registry_main
            return registry_main(args.registry_args)
        elif args.command == "registry-install":
            from .registry_client import install
            print("Installed:", install(args.origin, args.publisher, args.name, args.version, directory,
                                        args.trust_key, approve=args.approve, upgrade=args.upgrade))
        elif args.command == "init":
            from .workspace import initialize
            print(json.dumps({"created": initialize(directory)}))
        elif args.command == "studio":
            from .studio import start
            start(directory)
        elif args.command == "vault":
            from getpass import getpass
            from .vault import Vault
            password = getpass("Vault passphrase (at least 12 characters): ")
            if args.action == "init" and password != getpass("Confirm passphrase: "):
                raise WorkflowError("passphrases differ")
            with Vault(args.file, password, create=args.action == "init") as vault:
                if args.action == "list":
                    print(json.dumps(vault.names()))
                elif args.action in {"set", "delete"}:
                    if not args.name:
                        raise WorkflowError("vault entry name is required")
                    if args.action == "set":
                        vault.set(args.name, getpass("Secret value (not echoed): "))
                    else:
                        vault.delete(args.name)
                    print("Vault updated")
                else:
                    print("Encrypted vault created")
        elif args.command == "batch":
            from .batch import read_rows, run_batch
            wf = load_workflow(_path(directory, args.name))
            result = run_batch(wf, read_rows(args.file, wf), approve=args.approve, artifacts_dir=directory.parent / "runs")
            print(json.dumps(result, indent=2))
            return 0 if result["ok"] else 1
        elif args.command in {"schedule", "scheduler"}:
            from .scheduler import LocalScheduler
            store = LocalScheduler(directory)
            if args.command == "scheduler":
                store.serve(poll_seconds=args.poll_seconds, once=args.once)
            elif args.action == "list":
                print(json.dumps(store.list(), indent=2))
            elif not args.name:
                raise WorkflowError("schedule add/remove requires a workflow name")
            elif args.action == "add":
                print(json.dumps(store.add(args.name, every_minutes=args.every_minutes,
                    approve_writes=args.approve, data_file=args.data_file), indent=2))
            else:
                store.remove(args.name)
                print("Removed schedule:", args.name)
        elif args.command == "keygen":
            from .trust import generate_keypair
            generate_keypair(args.private, args.public)
            print("Keys created. Keep the private key outside the repository; share only the public key.")
        elif args.command == "inspect-desktop":
            from .desktop_access import inspect_window
            print(json.dumps(inspect_window(args.window, limit=args.limit), indent=2))
        elif args.command == "record-desktop":
            from .desktop import record_desktop
            print("Saved:", record_desktop(args.name, directory, smart=args.smart))
        elif args.command == "record-android":
            from .android import record_android
            print("Saved:", record_android(args.name, directory, serial=args.serial))
        elif args.command == "devices":
            from .android import adb_devices
            print(json.dumps({"authorizedDevices": adb_devices()}, indent=2))
        elif args.command == "pack":
            print("Packed:", pack_workflow(_path(directory, args.name), args.output, publisher=args.publisher, sign_key=args.sign_key, release_version=args.release_version))
        elif args.command == "verify":
            manifest, _ = inspect_package(args.package, trust_key=args.trust_key)
            print(json.dumps({"integrityValid": True, "signatureValid": manifest["packageVersion"] == 2, "publisherTrusted": args.trust_key is not None, "manifest": manifest}, indent=2))
        elif args.command == "install":
            print("Installed:", install_package(args.package, directory, approve=args.approve, trust_key=args.trust_key))
        elif args.command == "catalog":
            print(json.dumps(remote_catalog(args.catalog_url) if args.remote else local_catalog(args.catalog_dir), indent=2))
        elif args.command == "install-remote":
            print("Installed:", install_remote(args.name, directory, approve=args.approve, catalog_url=args.catalog_url, trust_key=args.trust_key))
        elif args.command == "record":
            print("No form values or passwords are stored. Inspect the workflow before sharing it.", file=sys.stderr)
            path = record(args.url, name=args.name, output_dir=directory, browser_path=args.browser_path, headless=args.headless)
            print(f"Saved: {path}\nNext: h2a check {args.name}")
        elif args.command == "list":
            print(json.dumps(list_workflows(directory), indent=2))
        elif args.command == "check":
            wf = load_workflow(_path(directory, args.name))
            print(f"Valid: {wf['name']} | {len(wf['steps'])} steps | {len(wf.get('inputs', {}))} inputs")
        elif args.command == "history":
            from .history import RunJournal
            print(json.dumps(RunJournal(directory.parent / ".h2a" / "history.db").list(), indent=2))
        elif args.command == "plan":
            from .models import validate_inputs
            wf = load_workflow(_path(directory, args.name))
            raw = args.data_file.read_text(encoding="utf-8") if args.data_file else args.data
            values = validate_inputs(wf, json.loads(raw))
            print(json.dumps({"workflow": wf["name"], "target": wf.get("target", "browser"),
                "permissions": wf.get("permissions", "write"), "stepCount": len(wf["steps"]),
                "actions": [step["action"] for step in wf["steps"]],
                "inputsSupplied": list(values), "inputsRedacted": True, "executed": False}, indent=2))
        elif args.command == "run":
            raw = args.data_file.read_text(encoding="utf-8") if args.data_file else args.data
            inputs = json.loads(raw)
            wf = load_workflow(_path(directory, args.name))
            if args.secret:
                if not args.vault:
                    raise WorkflowError("--secret requires --vault")
                from getpass import getpass
                from .vault import Vault
                with Vault(args.vault, getpass("Vault passphrase: ")) as vault:
                    for mapping in args.secret:
                        key, sep, entry = mapping.partition("=")
                        if not sep or not wf.get("inputs", {}).get(key, {}).get("secret"):
                            raise WorkflowError("--secret must reference a declared secret input as INPUT=ENTRY")
                        if key in inputs:
                            raise WorkflowError("input already supplied; refusing ambiguous secret mapping")
                        inputs[key] = vault.get(entry)
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
            if not any(directory.glob("*.json")):
                from .workspace import initialize
                initialize(directory, port=server.server_address[1])
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
