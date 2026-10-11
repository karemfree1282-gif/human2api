"""ADB-backed Android UI automation; no root or Android agent APK required.

All subprocess calls use argument arrays and never execute a shell on the host.
Selected device serials are validated and ambiguous device selections fail closed.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable
from xml.etree import ElementTree as ET

from .models import WorkflowError, PACKAGE_RE, SERIAL_RE, template

BBOX_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
KEYCODES = {"KEYCODE_BACK", "KEYCODE_HOME", "KEYCODE_ENTER", "KEYCODE_TAB", "KEYCODE_DPAD_UP", "KEYCODE_DPAD_DOWN", "KEYCODE_DPAD_LEFT", "KEYCODE_DPAD_RIGHT"}


def adb_devices(executable: str = "adb") -> list[str]:
    if not shutil.which(executable):
        raise WorkflowError("Android requires Android platform-tools (`adb`) on PATH")
    try:
        result = subprocess.run([executable, "devices"], capture_output=True, text=True, timeout=10, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise WorkflowError("could not list ADB devices") from exc
    devices = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device" and SERIAL_RE.fullmatch(parts[0]):
            devices.append(parts[0])
    return devices


class AndroidSession:
    def __init__(self, serial: str | None = None, *, executable: str = "adb") -> None:
        devices = adb_devices(executable)
        if serial:
            if not SERIAL_RE.fullmatch(serial) or serial not in devices:
                raise WorkflowError("specified Android device is not connected and authorized")
        elif len(devices) != 1:
            raise WorkflowError("connect exactly one authorized Android device or specify deviceSerial")
        self.serial = serial or devices[0]
        self.base = [executable, "-s", self.serial]

    def command(self, *args: str, binary: bool = False, timeout: int = 30) -> bytes | str:
        try:
            completed = subprocess.run([*self.base, *args], capture_output=True, timeout=timeout, check=True)
        except subprocess.CalledProcessError as exc:
            # adb stdout/stderr can contain sensitive device/app data; never disclose it.
            raise WorkflowError(f"Android ADB command failed (exit {exc.returncode})") from None
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise WorkflowError(f"Android device operation failed ({type(exc).__name__})") from None
        return completed.stdout if binary else completed.stdout.decode("utf-8", errors="replace")

    def dump_ui(self) -> ET.Element:
        # UIAutomator writes an XML file on the device; pull bytes via exec-out.
        self.command("shell", "uiautomator", "dump", "/sdcard/window.xml", timeout=30)
        xml = self.command("exec-out", "cat", "/sdcard/window.xml", binary=True)
        if len(xml) > 5 * 1024 * 1024:
            raise WorkflowError("Android UI hierarchy exceeds size limit")
        try:
            return ET.fromstring(xml)
        except ET.ParseError as exc:
            raise WorkflowError("Android UI hierarchy could not be parsed") from exc

    def find_node(self, selector: str, by: str = "text") -> ET.Element:
        attribute = {"text": "text", "resource-id": "resource-id", "content-desc": "content-desc"}.get(by)
        if attribute is None:
            raise WorkflowError("invalid Android UI selector kind")
        nodes = [n for n in self.dump_ui().iter("node") if n.get(attribute) == selector]
        if len(nodes) != 1:
            raise WorkflowError(f"Android selector must match exactly one element (matched {len(nodes)})")
        return nodes[0]

    def tap_node(self, selector: str, by: str = "text") -> None:
        node = self.find_node(selector, by)
        bounds = BBOX_RE.fullmatch(node.get("bounds", ""))
        if bounds is None:
            raise WorkflowError("Android element missing valid bounds")
        x1, y1, x2, y2 = map(int, bounds.groups())
        if x2 <= x1 or y2 <= y1:
            raise WorkflowError("Android element has empty bounds")
        self.command("shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2))


def encode_adb_text(value: str) -> str:
    """ADB input text is ASCII only and treats %s as space; do not invoke a shell."""
    if not value or len(value) > 1000 or not re.fullmatch(r"[A-Za-z0-9 .,_@-]+", value):
        raise WorkflowError("Android input_text supports ASCII letters, digits, spaces and . , _ @ - (max 1000)")
    return value.replace(" ", "%s")


def execute_android(workflow: dict[str, Any], values: dict[str, Any], artifacts: Path, on_step: Callable | None = None) -> dict[str, Any]:
    session = AndroidSession(workflow.get("deviceSerial"))
    outputs: dict[str, Any] = {}
    for i, step in enumerate(workflow["steps"], 1):
        action = step["action"]
        if on_step:
            on_step(i, action, "running")
        try:
            if action == "tap":
                session.command("shell", "input", "tap", str(step["x"]), str(step["y"]))
            elif action == "tap_text":
                session.tap_node(template(step["selector"], values), step.get("by", "text"))
            elif action == "swipe":
                session.command("shell", "input", "swipe", *[str(step[k]) for k in ("x", "y", "x2", "y2")], str(step.get("durationMs", 300)))
            elif action == "input_text":
                session.command("shell", "input", "text", encode_adb_text(template(step["value"], values)))
            elif action == "keyevent":
                if step["key"] not in KEYCODES:
                    raise WorkflowError("Android keyevent not on the safe allowlist")
                session.command("shell", "input", "keyevent", step["key"])
            elif action == "wait_ms":
                time.sleep(step["durationMs"] / 1000)
            elif action == "assert_text":
                wanted = template(step["text"], values)
                if not any(wanted in node.get("text", "") or wanted in node.get("content-desc", "") for node in session.dump_ui().iter("node")):
                    raise WorkflowError("expected UI text not visible")
            elif action == "extract_text":
                node = session.find_node(template(step["selector"], values), step.get("by", "text"))
                outputs[step["as"]] = (node.get("text", "") or node.get("content-desc", ""))[:10000]
            elif action == "screenshot":
                file = step.get("filename", f"android-{i}.png")
                if not file.lower().endswith(".png"):
                    file += ".png"
                image = session.command("exec-out", "screencap", "-p", binary=True)
                if not image.startswith(b"\x89PNG"):
                    raise WorkflowError("ADB did not return a PNG screenshot")
                dest = artifacts / file
                dest.write_bytes(image)
                outputs.setdefault("artifacts", []).append(str(dest))
            else:
                raise WorkflowError(f"unsupported Android action: {action}")
        except WorkflowError as exc:
            if on_step:
                on_step(i, action, "failed")
            raise WorkflowError(f"Android step {i} ({action}): {exc}") from None
        if on_step:
            on_step(i, action, "passed")
    return outputs


def record_android(name: str, output_dir: Path, *, serial: str | None = None) -> Path:
    """Guided command recorder. Actions execute on the user's selected phone.

    No screenshots/XML/typed contents are persisted in the workflow. Text inputs
    become required runtime parameters rather than recorded literal values.
    """
    from .models import save_workflow, workflow_file, NAME_RE
    if not NAME_RE.fullmatch(name):
        raise WorkflowError("invalid workflow name")
    path = workflow_file(output_dir, name)
    if path.exists():
        raise WorkflowError("workflow already exists")
    device = AndroidSession(serial)
    inputs: dict[str, Any] = {}
    steps: list[dict[str, Any]] = []
    print(f"Teaching Android device {device.serial}. Commands: tap X Y, tap-text TEXT, input NAME, back, wait MS, assert TEXT, screenshot, done")
    print("`input NAME` creates a required variable; type its demonstration value yourself on the phone if needed. NO text is captured.")
    while len(steps) < 250:
        line = input("h2a-android> ").strip()
        if line == "done":
            break
        args = line.split(maxsplit=2)
        try:
            if not args:
                continue
            if args[0] == "tap" and len(args) == 3:
                x, y = int(args[1]), int(args[2]); step = {"action": "tap", "x": x, "y": y}
                device.command("shell", "input", "tap", str(x), str(y))
            elif args[0] == "tap-text" and len(args) == 2:
                step = {"action": "tap_text", "selector": args[1], "by": "text"}
                device.tap_node(args[1])
            elif args[0] == "input" and len(args) == 2 and NAME_RE.fullmatch(args[1]):
                key = args[1]
                inputs[key] = {"type": "string", "required": True, "secret": True, "description": "Android text input"}
                step = {"action": "input_text", "value": "{{" + key + "}}"}
            elif args[0] == "back" and len(args) == 1:
                step = {"action": "keyevent", "key": "KEYCODE_BACK"}
                device.command("shell", "input", "keyevent", "KEYCODE_BACK")
            elif args[0] == "wait" and len(args) == 2:
                step = {"action": "wait_ms", "durationMs": int(args[1])}
            elif args[0] == "assert" and len(args) == 2:
                step = {"action": "assert_text", "text": args[1]}
            elif args[0] == "screenshot" and len(args) == 1:
                step = {"action": "screenshot"}
            else:
                print("Invalid command. Enter `done` to finish."); continue
            steps.append(step)
        except (ValueError, WorkflowError) as exc:
            print(f"Not recorded: {exc}")
    if not steps:
        raise WorkflowError("no Android actions recorded")
    data = {"schemaVersion": 1, "name": name, "description": "Guided Android workflow", "target": "android", "deviceSerial": device.serial, "permissions": "write", "inputs": inputs, "steps": steps}
    return save_workflow(path, data)
