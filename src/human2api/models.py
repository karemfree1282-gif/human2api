"""Portable, deliberately constrained workflows for browser, desktop and Android.

All workflow actions are allowlisted. Files never contain executable Python, shell
commands, JavaScript or arbitrary MCP tool invocations. Version 1 browser workflows
remain compatible with the original Human2API alpha.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SCHEMA_VERSION = 1
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
PARAM_RE = re.compile(r"{{\s*([a-z][a-z0-9_]*)\s*}}")
SERIAL_RE = re.compile(r"^[A-Za-z0-9._:-]{1,100}$")
PACKAGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+$")
BROWSER_ACTIONS = frozenset({"click", "fill", "select", "check", "wait", "assert_text", "extract_text", "download", "screenshot", "navigate", "press", "hover", "scroll", "drag", "wait_ms", "switch_tab"})
DESKTOP_ACTIONS = frozenset({"click", "double_click", "move", "scroll", "type_text", "hotkey", "press", "wait_ms", "screenshot", "assert_image"})
ANDROID_ACTIONS = frozenset({"tap", "tap_text", "swipe", "input_text", "keyevent", "wait_ms", "assert_text", "extract_text", "screenshot"})
ACTIONS = BROWSER_ACTIONS | DESKTOP_ACTIONS | ANDROID_ACTIONS
TARGET_ACTIONS = {"browser": BROWSER_ACTIONS, "desktop": DESKTOP_ACTIONS, "android": ANDROID_ACTIONS}
INPUT_TYPES = frozenset({"string", "number", "boolean"})
MAX_STEPS = 250
MAX_WORKFLOW_BYTES = 256 * 1024
WRITE_ACTIONS = frozenset({"click", "fill", "select", "check", "download", "press", "drag", "double_click", "move", "scroll", "type_text", "hotkey", "tap", "tap_text", "swipe", "input_text", "keyevent"})


class WorkflowError(ValueError):
    """Invalid or unsafe workflow input."""


def _is_http(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname) and not (parsed.username or parsed.password)


def _check_string(value: Any, name: str, *, max_length: int = 2048) -> str:
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise WorkflowError(f"{name} must be a nonempty string (up to {max_length} characters)")
    return value


def _safe_filename(name: Any) -> str:
    name = _check_string(name, "filename", max_length=128)
    if name in {".", ".."} or name.startswith(".") or name != Path(name).name or "\\" in name or "/" in name or "{{" in name:
        raise WorkflowError("filename must be a simple basename without template expressions")
    return name


def _validate_value(key: str, value: Any, field_type: str) -> None:
    if field_type == "string" and not isinstance(value, str):
        raise WorkflowError(f"input {key}: must be a string")
    if field_type == "number" and (type(value) not in (int, float) or isinstance(value, bool) or (not math.isfinite(value) or abs(value) > 1e15)):
        raise WorkflowError(f"input {key}: must be a finite number")
    if field_type == "boolean" and not isinstance(value, bool):
        raise WorkflowError(f"input {key}: must be boolean")


def _int_between(value: Any, name: str, lo: int, hi: int) -> None:
    if type(value) is not int or not lo <= value <= hi:
        raise WorkflowError(f"{name} must be an integer between {lo} and {hi}")


def validate_workflow(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise WorkflowError("workflow must be a JSON object")
    if raw.get("schemaVersion") != SCHEMA_VERSION:
        raise WorkflowError(f"schemaVersion must be {SCHEMA_VERSION}")
    name = _check_string(raw.get("name"), "name", max_length=63)
    if not NAME_RE.fullmatch(name):
        raise WorkflowError("name must match [a-z][a-z0-9_]*")
    _check_string(raw.get("description"), "description", max_length=300)
    target = raw.get("target", "browser")
    if target not in TARGET_ACTIONS:
        raise WorkflowError("target must be browser, desktop or android")
    top_fields = {"$schema", "schemaVersion", "name", "description", "target", "startUrl", "permissions", "allowedHosts", "inputs", "steps", "deviceSerial", "appPackage"}
    unknown_top = set(raw) - top_fields
    if unknown_top:
        raise WorkflowError("unknown workflow fields: " + ", ".join(sorted(unknown_top)))
    if target == "browser":
        start_url = _check_string(raw.get("startUrl"), "startUrl", max_length=2048)
        if not _is_http(start_url):
            raise WorkflowError("startUrl must be a valid HTTP(S) URL without embedded credentials")
        if urlparse(start_url).fragment:
            raise WorkflowError("startUrl cannot contain fragments")
        allowed_hosts = raw.get("allowedHosts") or [urlparse(start_url).hostname]
        if not isinstance(allowed_hosts, list) or not allowed_hosts or len(allowed_hosts) > 30:
            raise WorkflowError("allowedHosts must be a nonempty list of at most 30 hostnames")
        for host in allowed_hosts:
            if not isinstance(host, str) or not host or host != host.lower() or any(x in host for x in ["/", "*", ":", "@", " "]):
                raise WorkflowError("allowedHosts must contain exact lowercase hostnames without ports or wildcards")
        if urlparse(start_url).hostname not in allowed_hosts:
            raise WorkflowError("startUrl hostname must be in allowedHosts")
        if "deviceSerial" in raw or "appPackage" in raw:
            raise WorkflowError("deviceSerial and appPackage require target android")
    else:
        if "startUrl" in raw or "allowedHosts" in raw:
            raise WorkflowError("startUrl/allowedHosts are only valid for browser workflows")
        if target == "android":
            for field, pattern in (("deviceSerial", SERIAL_RE), ("appPackage", PACKAGE_RE)):
                if field in raw and (not isinstance(raw[field], str) or not pattern.fullmatch(raw[field])):
                    raise WorkflowError(f"{field} is invalid")
        elif "deviceSerial" in raw or "appPackage" in raw:
            raise WorkflowError("deviceSerial and appPackage require target android")
    permission = raw.get("permissions", "write")
    if permission not in {"read", "write"}:
        raise WorkflowError("permissions must be 'read' or 'write'")
    inputs = raw.get("inputs", {})
    if not isinstance(inputs, dict) or len(inputs) > 80:
        raise WorkflowError("inputs must be a map with at most 80 fields")
    for key, spec in inputs.items():
        if not isinstance(key, str) or not NAME_RE.fullmatch(key) or not isinstance(spec, dict):
            raise WorkflowError(f"invalid input declaration: {key!r}")
        if set(spec) - {"type", "required", "secret", "description", "default"}:
            raise WorkflowError(f"input {key}: unknown fields")
        if spec.get("type", "string") not in INPUT_TYPES:
            raise WorkflowError(f"input {key}: unsupported type")
        if "required" in spec and not isinstance(spec["required"], bool):
            raise WorkflowError(f"input {key}: required must be boolean")
        if "secret" in spec and not isinstance(spec["secret"], bool):
            raise WorkflowError(f"input {key}: secret must be boolean")
        if "description" in spec and (not isinstance(spec["description"], str) or len(spec["description"]) > 200):
            raise WorkflowError(f"input {key}: invalid description")
        if "default" in spec:
            _validate_value(key, spec["default"], spec.get("type", "string"))
            if spec.get("secret"):
                raise WorkflowError(f"input {key}: secret inputs must never have saved defaults")
    steps = raw.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        raise WorkflowError(f"steps must contain 1-{MAX_STEPS} actions")
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict) or step.get("action") not in TARGET_ACTIONS[target]:
            raise WorkflowError(f"step {index}: unrecognized action for {target}")
        action = step["action"]
        browser_with_selector = {"click", "fill", "select", "check", "wait", "assert_text", "extract_text", "download", "press", "hover", "scroll", "drag"}
        if target == "browser" and action in browser_with_selector:
            _check_string(step.get("selector"), f"step {index} selector")
        if target == "browser" and action == "navigate":
            _check_string(step.get("url"), f"step {index} url")
        if action in {"fill", "select", "type_text", "input_text"}:
            value = step.get("value")
            if not isinstance(value, str) or len(value) > 10000:
                raise WorkflowError(f"step {index} value must be a string of at most 10000 characters")
        if action == "check" and not isinstance(step.get("checked"), (bool, str)):
            raise WorkflowError(f"step {index}: checked must be a bool or template string")
        if action == "assert_text":
            _check_string(step.get("text"), f"step {index} text")
        if action == "extract_text":
            output = _check_string(step.get("as"), f"step {index} as", max_length=63)
            if not NAME_RE.fullmatch(output):
                raise WorkflowError(f"step {index}: invalid output name")
        if action in {"screenshot", "download"} and "filename" in step:
            _safe_filename(step["filename"])
        if action == "assert_image":
            _safe_filename(step.get("image"))
        if action in {"press", "keyevent"}:
            _check_string(step.get("key"), f"step {index} key", max_length=45)
        if action == "hotkey":
            keys = step.get("keys")
            if not isinstance(keys, list) or not 1 <= len(keys) <= 5 or not all(isinstance(k, str) and re.fullmatch(r"[a-z0-9_]{1,20}", k) for k in keys):
                raise WorkflowError(f"step {index}: invalid hotkey list")
        if target == "desktop":
            if action in {"click", "double_click", "move"}:
                for dim in ("x", "y"):
                    _int_between(step.get(dim), f"step {index} {dim}", 0, 16384)
            if action == "scroll":
                _int_between(step.get("delta"), f"step {index} delta", -100, 100)
        if target == "android":
            if action in {"tap", "swipe"}:
                for dim in ("x", "y"):
                    _int_between(step.get(dim), f"step {index} {dim}", 0, 16384)
            if action == "swipe":
                for dim in ("x2", "y2"):
                    _int_between(step.get(dim), f"step {index} {dim}", 0, 16384)
            if action in {"tap_text", "extract_text"}:
                _check_string(step.get("selector"), f"step {index} selector", max_length=300)
        common = {"action", "timeoutMs"}
        extras = {
            "click": {"selector", "alternatives", "x", "y", "role", "label", "textHint"},
            "double_click": {"x", "y"}, "move": {"x", "y"},
            "fill": {"selector", "alternatives", "value", "role", "label", "textHint"},
            "select": {"selector", "alternatives", "value", "role", "label", "textHint"},
            "check": {"selector", "alternatives", "checked", "role", "label", "textHint"},
            "wait": {"selector", "alternatives", "role", "label", "textHint"},
            "assert_text": {"selector", "alternatives", "text", "role", "label", "textHint"},
            "extract_text": {"selector", "alternatives", "as", "role", "label", "textHint"},
            "download": {"selector", "alternatives", "filename", "role", "label", "textHint"},
            "screenshot": {"filename"}, "navigate": {"url"},
            "press": {"selector", "alternatives", "key", "role", "label", "textHint"},
            "hover": {"selector", "alternatives", "role", "label", "textHint"},
            "scroll": {"selector", "alternatives", "delta"},
            "drag": {"selector", "alternatives", "targetSelector", "role", "label", "textHint"},
            "wait_ms": {"durationMs"}, "switch_tab": {"index"},
            "type_text": {"value"}, "hotkey": {"keys"},
            "assert_image": {"image"},
            "tap": {"x", "y"}, "tap_text": {"selector", "by"},
            "swipe": {"x", "y", "x2", "y2", "durationMs"},
            "input_text": {"value"}, "keyevent": {"key"},
        }
        if target == "browser" and action in browser_with_selector:
            extras[action].add("frame")
        unknown = set(step) - common - extras[action]
        if unknown:
            raise WorkflowError(f"step {index}: unknown fields {', '.join(sorted(unknown))}")
        if "alternatives" in step and (not isinstance(step["alternatives"], list) or len(step["alternatives"]) > 8 or not all(isinstance(s, str) and 0 < len(s) < 2048 for s in step["alternatives"])):
            raise WorkflowError(f"step {index}: alternatives must be a small array of selectors")
        if "timeoutMs" in step:
            _int_between(step["timeoutMs"], f"step {index} timeoutMs", 100, 120000)
        if "durationMs" in step:
            _int_between(step["durationMs"], f"step {index} durationMs", 100, 120000)
        if "index" in step:
            _int_between(step["index"], f"step {index} index", 0, 20)
        if "delta" in step and target == "browser":
            _int_between(step["delta"], f"step {index} delta", -100, 100)
        if "targetSelector" in step:
            _check_string(step["targetSelector"], f"step {index} targetSelector")
        if "frame" in step and target != "browser":
            raise WorkflowError(f"step {index}: frame selectors are browser-only")
        if "frame" in step:
            _check_string(step["frame"], f"step {index} frame", max_length=2048)
        if "by" in step and step["by"] not in {"text", "resource-id", "content-desc"}:
            raise WorkflowError(f"step {index}: invalid Android selector kind")
        for field in ("role", "label", "textHint"):
            if field in step:
                _check_string(step[field], f"step {index} {field}", max_length=150)
    referenced: set[str] = set()
    for step in steps:
        for value in step.values():
            if isinstance(value, str):
                referenced.update(PARAM_RE.findall(value))
    missing = referenced - inputs.keys()
    if missing:
        raise WorkflowError("undeclared template inputs: " + ", ".join(sorted(missing)))
    if permission == "read" and any(s["action"] in WRITE_ACTIONS for s in steps):
        raise WorkflowError("read-only workflow cannot include write actions")
    return raw


def validate_inputs(workflow: dict[str, Any], provided: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(provided, dict):
        raise WorkflowError("workflow arguments must be a JSON object")
    specs = workflow.get("inputs", {})
    unknown = set(provided) - set(specs)
    if unknown:
        raise WorkflowError("unknown input(s): " + ", ".join(sorted(unknown)))
    clean: dict[str, Any] = {}
    for key, spec in specs.items():
        if key in provided:
            value = provided[key]
        elif "default" in spec:
            value = spec["default"]
        elif spec.get("required", True):
            raise WorkflowError(f"required input missing: {key}")
        else:
            continue
        _validate_value(key, value, spec.get("type", "string"))
        clean[key] = value
    return clean


def template(value: str, inputs: dict[str, Any]) -> str:
    def substitute(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in inputs:
            raise WorkflowError(f"template input not supplied: {key}")
        value = inputs[key]
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)
    return PARAM_RE.sub(substitute, value)


def load_workflow(path: Path | str) -> dict[str, Any]:
    path = Path(path)
    if path.is_symlink():
        raise WorkflowError("refusing to load a symlink workflow")
    if path.stat().st_size > MAX_WORKFLOW_BYTES:
        raise WorkflowError("workflow JSON exceeds size limit")
    try:
        return validate_workflow(json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as exc:
        raise WorkflowError(f"invalid JSON: {exc}") from exc


def save_workflow(path: Path | str, workflow: dict[str, Any]) -> Path:
    validate_workflow(workflow)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise WorkflowError("refusing to overwrite a symlink")
    payload = json.dumps(workflow, indent=2, ensure_ascii=False) + "\n"
    if len(payload.encode("utf-8")) > MAX_WORKFLOW_BYTES:
        raise WorkflowError("workflow JSON exceeds size limit")
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(payload, encoding="utf-8")
    temp.replace(path)
    return path


def list_workflows(directory: Path | str) -> list[dict[str, Any]]:
    directory = Path(directory)
    if not directory.exists():
        return []
    found = []
    for file in sorted(directory.glob("*.json")):
        if file.is_symlink():
            continue
        try:
            data = load_workflow(file)
            found.append({"name": data["name"], "description": data["description"], "target": data.get("target", "browser"), "permissions": data.get("permissions", "write"), "inputs": len(data.get("inputs", {})), "steps": len(data["steps"]), "file": str(file)})
        except (WorkflowError, ValueError, OSError):
            continue
    return found


def workflow_file(directory: Path | str, name: str) -> Path:
    if not NAME_RE.fullmatch(name):
        raise WorkflowError("invalid workflow name")
    return Path(directory) / (name + ".json")


def secret_redact(message: str, workflow: dict[str, Any], inputs: dict[str, Any]) -> str:
    for key, spec in workflow.get("inputs", {}).items():
        if spec.get("secret") and key in inputs:
            value = str(inputs[key])
            if value:
                message = message.replace(value, "[REDACTED]")
    return message[:600]


def input_json_schema(workflow: dict[str, Any]) -> dict[str, Any]:
    properties = {}
    required = []
    for key, spec in workflow.get("inputs", {}).items():
        props: dict[str, Any] = {"type": spec.get("type", "string")}
        if "description" in spec:
            props["description"] = spec["description"]
        if "default" in spec:
            props["default"] = spec["default"]
        if spec.get("secret"):
            props["writeOnly"] = True
        properties[key] = props
        if spec.get("required", True) and "default" not in spec:
            required.append(key)
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}
