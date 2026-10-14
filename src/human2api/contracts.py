"""Formal execution contracts, redaction helpers, and security policy checks."""

from __future__ import annotations

import json
import pathlib
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from human2api.models import Workflow, WorkflowStep

SENSITIVE_KEY_NAMES = {
    "password",
    "pass",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "private_key",
    "credit_card",
    "cvv",
    "pin",
    "otp",
    "authorization",
}

REDACTED_PLACEHOLDER = "[REDACTED]"


def is_sensitive_field_name(name: Optional[str]) -> bool:
    if not name:
        return False
    norm = re.sub(r"[^a-z0-9_]", "_", name.lower()).strip("_")
    for token in SENSITIVE_KEY_NAMES:
        if norm == token or norm.endswith(f"_{token}") or norm.startswith(f"{token}_") or token in norm.split("_"):
            return True
    return False


def redact_secrets(text: str, secret_values: Optional[Set[str]] = None) -> str:
    """Ensure no known secret value or bearer token leaks into logs or error messages."""
    if not text:
        return text
    out = str(text)
    if secret_values:
        for val in sorted(secret_values, key=len, reverse=True):
            if val and len(val) >= 3:
                out = out.replace(val, REDACTED_PLACEHOLDER)
    # Redact Authorization Bearer / token query params
    out = re.sub(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1" + REDACTED_PLACEHOLDER, out, flags=re.IGNORECASE)
    out = re.sub(
        r"((?:password|secret|token|api_key|apikey)\s*[=:]\s*)([^\s&\"',;]+)",
        r"\1" + REDACTED_PLACEHOLDER,
        out,
        flags=re.IGNORECASE,
    )
    return out


def validate_url_against_policy(
    url: str,
    allowed_hosts: List[str],
    network_policy: str = "strict",
) -> None:
    """Validate target URL against workflow networkPolicy and allowedHosts."""
    parsed = urllib.parse.urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme in ("javascript", "vbscript", "file"):
        raise PermissionError(f"Disallowed URL scheme in workflow navigation: {scheme!r}")
    if scheme == "about" and url == "about:blank":
        return
    if scheme not in ("http", "https", "data"):
        raise PermissionError(f"Unsupported URL scheme: {scheme!r}")
    if scheme == "data":
        return

    host = (parsed.hostname or "").lower()
    if not host:
        raise PermissionError(f"URL is missing hostname: {url!r}")

    if network_policy in ("strict", "navigation-only") and allowed_hosts:
        normalized_allowed = {h.lower().strip() for h in allowed_hosts if h.strip()}
        # Treat local loopback aliases equivalently when loopback is explicitly allowed
        loopback_aliases = {"127.0.0.1", "127.0.0.2", "localhost", "::1"}
        if normalized_allowed & loopback_aliases and host in loopback_aliases:
            return
        matched = False
        for pattern in normalized_allowed:
            if pattern == host:
                matched = True
                break
            if pattern.startswith("*.") and host.endswith(pattern[1:]):
                matched = True
                break
        if not matched:
            raise PermissionError(
                f"Host {host!r} is not permitted by allowedHosts={sorted(normalized_allowed)} under networkPolicy={network_policy!r}"
            )


def safe_resolve_user_path(base_dir: pathlib.Path, user_path: str) -> pathlib.Path:
    """Resolve a file upload/download path strictly inside base_dir, preventing Path Traversal and symlink escapes."""
    if not user_path or "\x00" in user_path:
        raise PermissionError("Invalid or empty file path.")
    base_resolved = base_dir.resolve()
    candidate = (base_resolved / user_path).resolve()
    try:
        candidate.relative_to(base_resolved)
    except ValueError as exc:
        raise PermissionError(f"Path traversal blocked: {user_path!r} escapes {base_resolved}") from exc
    return candidate


@dataclass
class StepExecutionRecord:
    step_id: str
    action: str
    status: str  # "passed", "failed", "healed", "cancelled"
    duration_ms: float
    selector_used: Optional[str] = None
    healing_tier: Optional[int] = None
    extracted_value: Any = None
    error: Optional[str] = None

    def to_dict(self, secret_values: Optional[Set[str]] = None) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "action": self.action,
            "status": self.status,
            "duration_ms": round(self.duration_ms, 2),
            "selector_used": self.selector_used,
            "healing_tier": self.healing_tier,
            "extracted_value": redact_secrets(str(self.extracted_value), secret_values)
            if self.extracted_value is not None
            else None,
            "error": redact_secrets(self.error, secret_values) if self.error else None,
        }


@dataclass
class WorkflowRunReport:
    workflow_name: str
    target: str
    status: str  # "passed", "failed", "cancelled"
    duration_ms: float
    steps: List[StepExecutionRecord] = field(default_factory=list)
    assertions_passed: int = 0
    assertions_failed: int = 0
    healing_events: List[Dict[str, Any]] = field(default_factory=list)
    outputs: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self, secret_values: Optional[Set[str]] = None) -> Dict[str, Any]:
        return {
            "workflow_name": self.workflow_name,
            "target": self.target,
            "status": self.status,
            "duration_ms": round(self.duration_ms, 2),
            "steps": [s.to_dict(secret_values) for s in self.steps],
            "assertions_passed": self.assertions_passed,
            "assertions_failed": self.assertions_failed,
            "healing_events": self.healing_events,
            "outputs": {
                k: redact_secrets(str(v), secret_values) if isinstance(v, str) else v
                for k, v in self.outputs.items()
            },
            "error": redact_secrets(self.error, secret_values) if self.error else None,
        }
