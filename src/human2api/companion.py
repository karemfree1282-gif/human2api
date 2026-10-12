"""Authenticated loopback client for the consent-based Android companion.

A user must enable the app's service, select a package, arm the session, and
supply its short-lived token. This module never changes device permissions.
"""
from __future__ import annotations
import json
import os
import re
import secrets
from typing import Any
from urllib.request import Request, build_opener

from .healing import _NoRedirect
from .models import WorkflowError, PACKAGE_RE


def action(package: str, name: str, *, selector: str = "", by: str = "resource-id", value: str | None = None) -> dict[str, Any]:
    token = os.environ.get("H2A_ANDROID_BRIDGE_TOKEN", "")
    port = os.environ.get("H2A_ANDROID_BRIDGE_PORT", "8766")
    if not re.fullmatch(r"[a-f0-9]{64}", token):
        raise WorkflowError("Arm the Android companion and set its short-lived H2A_ANDROID_BRIDGE_TOKEN")
    if not port.isdigit() or not 1024 <= int(port) <= 65535:
        raise WorkflowError("invalid Android bridge port")
    if not PACKAGE_RE.fullmatch(package) or name not in {"click", "set_text", "back", "scroll_forward", "scroll_backward"}:
        raise WorkflowError("invalid companion action or package")
    if by not in {"resource-id", "content-desc"} or len(selector) > 300:
        raise WorkflowError("companion requires a resource-id or content-desc selector")
    payload: dict[str, Any] = {"package": package, "action": name, "selector": selector,
                               "by": by, "requestId": secrets.token_hex(16)}
    if value is not None:
        if not isinstance(value, str) or len(value) > 10000:
            raise WorkflowError("invalid companion text")
        payload["value"] = value
    request = Request(f"http://127.0.0.1:{port}/action", data=json.dumps(payload).encode("utf-8"),
                      headers={"Content-Type": "application/json", "X-H2A-Token": token}, method="POST")
    try:
        with build_opener(_NoRedirect()).open(request, timeout=15) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError("response too large")
        result = json.loads(raw)
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise ValueError("operation rejected")
        return {"ok": True}
    except (OSError, ValueError, TypeError) as exc:
        raise WorkflowError("Android companion rejected or could not confirm the action; inspect the phone before retrying") from None
