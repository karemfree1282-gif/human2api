"""Execution context, cancellation tokens, variable interpolation, and assertion verification."""

from __future__ import annotations

import os
import pathlib
import re
import threading
import time
from typing import Any, Dict, Optional, Set, Tuple

from human2api.contracts import REDACTED_PLACEHOLDER, safe_resolve_user_path
from human2api.models import SECRET_REF_PATTERN, AssertionSpec, Workflow
from human2api.vault import SecretVault


class WorkflowCancelledError(RuntimeError):
    """Raised when a running workflow is cooperatively or immediately cancelled."""


class AssertionFailureError(AssertionError):
    """Raised when a workflow step or post-condition assertion fails."""


class CancellationToken:
    """Thread-safe cooperative and immediate cancellation token."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._reason: str = "Cancelled by user or timeout."
        self._callbacks = []
        self._lock = threading.Lock()

    def cancel(self, reason: str = "Cancelled by user request.") -> None:
        with self._lock:
            self._reason = reason
            self._event.set()
            callbacks = list(self._callbacks)
        for cb in callbacks:
            try:
                cb()
            except Exception:
                pass

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        return self._reason

    def check(self) -> None:
        if self._event.is_set():
            raise WorkflowCancelledError(self._reason)

    def register_callback(self, fn) -> None:
        with self._lock:
            if self._event.is_set():
                try:
                    fn()
                except Exception:
                    pass
            else:
                self._callbacks.append(fn)


def resolve_step_parameters(
    raw_value: Optional[str],
    workflow: Workflow,
    runtime_inputs: Dict[str, Any],
    vault: Optional[SecretVault] = None,
) -> Tuple[Optional[str], Set[str]]:
    """Interpolate ${input:NAME} and ${secret:NAME} tokens and return (resolved_string, secret_values_used)."""
    if raw_value is None:
        return None, set()
    if not isinstance(raw_value, str):
        return str(raw_value), set()

    secrets_used: Set[str] = set()

    def _replacer(match: re.Match) -> str:
        kind = match.group(1)
        key = match.group(2)
        if kind == "secret":
            if key in runtime_inputs and runtime_inputs[key] is not None:
                val = str(runtime_inputs[key])
                secrets_used.add(val)
                return val
            if vault is not None and vault.is_unlocked():
                val = vault.get_secret(key)
                secrets_used.add(val)
                return val
            raise PermissionError(f"Secret {key!r} required by workflow is not provided and Vault is locked/missing.")
        else:
            if key in runtime_inputs and runtime_inputs[key] is not None:
                val = str(runtime_inputs[key])
                spec = workflow.inputs.get(key)
                if spec and (spec.sensitive or spec.type == "secret"):
                    secrets_used.add(val)
                return val
            spec = workflow.inputs.get(key)
            if spec and spec.default is not None:
                return str(spec.default)
            if spec and not spec.required:
                return ""
            raise ValueError(f"Missing required workflow input parameter: {key!r}")

    resolved = SECRET_REF_PATTERN.sub(_replacer, raw_value)
    return resolved, secrets_used


def evaluate_assertion(
    spec: AssertionSpec,
    actual_value: Any,
) -> None:
    """Verify an assertion against an actual observed value."""
    expected = spec.expected
    if spec.type == "assert_visible":
        if not bool(actual_value):
            raise AssertionFailureError(f"Assertion failed: expected selector {spec.selector!r} to be visible.")
        return

    if spec.type == "assert_count":
        actual_int = int(actual_value or 0)
        expected_int = int(expected or 0)
        if actual_int != expected_int:
            raise AssertionFailureError(
                f"Assertion assert_count failed for {spec.selector!r}: expected {expected_int}, got {actual_int}."
            )
        return

    actual_str = "" if actual_value is None else str(actual_value)
    expected_str = "" if expected is None else str(expected)

    if spec.match == "exact":
        if actual_str.strip() != expected_str.strip():
            raise AssertionFailureError(
                f"Assertion {spec.type} (exact) failed: expected {expected_str!r}, got {actual_str!r}."
            )
    elif spec.match == "regex":
        if not re.search(expected_str, actual_str):
            raise AssertionFailureError(
                f"Assertion {spec.type} (regex) failed: pattern {expected_str!r} did not match {actual_str!r}."
            )
    else:  # contains
        if expected_str not in actual_str:
            raise AssertionFailureError(
                f"Assertion {spec.type} (contains) failed: expected {expected_str!r} inside {actual_str!r}."
            )


def check_write_approval(workflow: Workflow, allow_write: bool = False) -> None:
    """Enforce explicit write approval for mutating workflows."""
    env_write = os.environ.get("H2A_ALLOW_WRITE", "").strip() == "1"
    if workflow.requires_write_approval() and not (allow_write or env_write):
        raise PermissionError(
            f"Workflow {workflow.name!r} contains write/mutating actions and requires explicit write approval (allow_write=True or H2A_ALLOW_WRITE=1)."
        )
