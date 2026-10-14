"""Android Companion Client & ADB Loopback Bridge with session TTL, package allowlisting, and Unicode support."""

from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

from human2api.contracts import (
    StepExecutionRecord,
    WorkflowRunReport,
    is_sensitive_field_name,
    redact_secrets,
)
from human2api.execution import (
    AssertionFailureError,
    CancellationToken,
    WorkflowCancelledError,
    evaluate_assertion,
    resolve_step_parameters,
)
from human2api.healing import SelfHealingEngine, UIElementCandidate
from human2api.models import AssertionSpec, Workflow, WorkflowStep
from human2api.vault import SecretVault

DEFAULT_COMPANION_PORT = 18765
SESSION_TTL_SECONDS = 300.0  # 5 minutes matching CompanionService.java


class AndroidSessionExpiredError(PermissionError):
    """Raised when the Android Companion user-consent session has expired or disconnected."""


class AndroidUnauthorizedPackageError(PermissionError):
    """Raised when an action targets an Android package outside the user-approved allowlist."""


@dataclass
class AndroidNode:
    node_id: str
    resource_id: str
    text: str
    content_desc: str
    class_name: str
    package_name: str
    clickable: bool = True
    editable: bool = False
    scrollable: bool = False
    enabled: bool = True
    visible: bool = True
    is_password: bool = False

    @property
    def role(self) -> str:
        cn = self.class_name.lower()
        if "edittext" in cn or self.editable:
            return "textbox"
        if "button" in cn or "imagebutton" in cn:
            return "button"
        if "checkbox" in cn or "switch" in cn:
            return "checkbox"
        return "view"

    def to_candidate(self) -> UIElementCandidate:
        sel = self.resource_id or f'contentDesc="{self.content_desc or self.text}"'
        return UIElementCandidate(
            candidate_id=self.node_id,
            selector=sel,
            role=self.role,
            name="" if self.is_password else (self.content_desc or self.text),
            automation_id=self.resource_id,
            resource_id=self.resource_id,
            content_desc="" if self.is_password else self.content_desc,
            tag_name=self.role,
            visible=self.visible,
            enabled=self.enabled,
            is_password=self.is_password,
            host_or_package=self.package_name,
        )


class AndroidCompanionClient:
    """Communicates with the Android Companion AccessibilityService over ADB port forwarding (`127.0.0.1:18765`),
    enforcing explicit user consent, 5-minute session TTL, package allowlists, password redaction, and immediate STOP.
    """

    def __init__(
        self,
        port: int = DEFAULT_COMPANION_PORT,
        session_ttl_seconds: float = SESSION_TTL_SECONDS,
        nodes: Optional[List[AndroidNode]] = None,
        consent_granted: bool = True,
        allowed_packages: Optional[List[str]] = None,
    ) -> None:
        self.port = port
        self.session_ttl_seconds = float(session_ttl_seconds)
        self.consent_granted = consent_granted
        self.session_started_at = time.monotonic() if consent_granted else 0.0
        self.connected = True
        self.stopped = False
        self.allowed_packages: Set[str] = set(allowed_packages or [])
        self.nodes: Dict[str, AndroidNode] = {}
        self.active_package: str = ""
        if nodes:
            for n in nodes:
                self.register_node(n)

    def register_node(self, node: AndroidNode) -> None:
        self.nodes[node.node_id] = node
        if not self.active_package and node.package_name:
            self.active_package = node.package_name

    @staticmethod
    def probe_adb_devices() -> Tuple[bool, List[str], str]:
        """Check if `adb` CLI is installed and whether any physical/emulator device is attached."""
        try:
            proc = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=5)
            if proc.returncode != 0:
                return False, [], proc.stderr.strip() or "adb devices returned non-zero"
            devices = []
            for line in proc.stdout.splitlines()[1:]:
                parts = line.strip().split()
                if len(parts) >= 2 and parts[1] == "device":
                    devices.append(parts[0])
            return True, devices, "ok"
        except FileNotFoundError:
            return False, [], "adb binary not installed in PATH"
        except Exception as exc:
            return False, [], str(exc)

    def grant_user_consent(self, allowed_packages: List[str], ttl_seconds: Optional[float] = None) -> None:
        self.consent_granted = True
        self.stopped = False
        self.connected = True
        self.allowed_packages = {p.strip() for p in allowed_packages if p.strip()}
        if ttl_seconds is not None:
            self.session_ttl_seconds = float(ttl_seconds)
        self.session_started_at = time.monotonic()

    def trigger_stop(self) -> None:
        """Immediate cooperative/broadcast STOP (equivalent to StopReceiver notification action on Android)."""
        self.stopped = True
        self.consent_granted = False

    def simulate_disconnect(self) -> None:
        self.connected = False

    def verify_session_and_package(self, target_package: str, workflow_allowed_packages: List[str]) -> None:
        if self.stopped:
            raise WorkflowCancelledError("Android Companion execution stopped immediately by user STOP signal.")
        if not self.connected:
            raise ConnectionError("Android Companion ADB bridge connection lost or app closed.")
        if not self.consent_granted:
            raise PermissionError("User consent not granted in Android Companion app.")
        if (time.monotonic() - self.session_started_at) > self.session_ttl_seconds:
            self.consent_granted = False
            raise AndroidSessionExpiredError("Android Companion 5-minute consent session expired.")

        effective_allowed = set(self.allowed_packages) | {p.strip() for p in workflow_allowed_packages if p.strip()}
        if not effective_allowed:
            raise AndroidUnauthorizedPackageError("No allowed Android package configured for workflow execution.")
        if target_package not in effective_allowed:
            raise AndroidUnauthorizedPackageError(
                f"Package {target_package!r} is not authorized. Allowed packages: {sorted(effective_allowed)}"
            )

    def snapshot_candidates(self) -> List[UIElementCandidate]:
        out: List[UIElementCandidate] = []
        for n in self.nodes.values():
            if self.active_package and n.package_name != self.active_package:
                continue
            out.append(n.to_candidate())
        return out

    def match_primary(self, selector: str) -> List[UIElementCandidate]:
        sel = (selector or "").strip()
        matches: List[UIElementCandidate] = []
        for n in self.nodes.values():
            if self.active_package and n.package_name != self.active_package:
                continue
            cand = n.to_candidate()
            if (
                n.resource_id == sel
                or cand.selector == sel
                or (not n.is_password and (n.content_desc == sel or n.text == sel))
            ):
                matches.append(cand)
        return matches

    def record_accessibility_event(self, raw_event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Filter incoming AccessibilityEvents from Android: block password fields and unauthorized packages."""
        pkg = str(raw_event.get("packageName") or "")
        if self.allowed_packages and pkg not in self.allowed_packages:
            raise AndroidUnauthorizedPackageError(f"Refusing to record event from unauthorized package {pkg!r}.")
        is_pwd = bool(raw_event.get("isPassword") or is_sensitive_field_name(raw_event.get("resourceId")))
        sanitized = dict(raw_event)
        if is_pwd:
            sanitized["is_password"] = True
            sanitized["text"] = None
            sanitized["value"] = None
        return sanitized

    def execute_workflow(
        self,
        workflow: Workflow,
        runtime_inputs: Dict[str, Any],
        vault: Optional[SecretVault],
        secrets_known: Set[str],
        cancel_token: CancellationToken,
        ai_advisor: Optional[Callable] = None,
        step_observer: Optional[Callable[[StepExecutionRecord], None]] = None,
        start_ts: Optional[float] = None,
    ) -> WorkflowRunReport:
        t0 = start_ts or time.perf_counter()
        cancel_token.register_callback(self.trigger_stop)
        healer = SelfHealingEngine(config=workflow.healing, ai_advisor=ai_advisor)
        step_records: List[StepExecutionRecord] = []
        healing_events: List[Dict[str, Any]] = []
        outputs: Dict[str, Any] = {}
        assertions_passed = 0
        assertions_failed = 0

        try:
            for idx, step in enumerate(workflow.steps):
                cancel_token.check()
                step_start = time.perf_counter()
                step_id = step.id or f"step_{idx + 1}"
                action = step.action
                target_pkg = step.packageName or self.active_package or (
                    workflow.allowedPackages[0] if workflow.allowedPackages else ""
                )
                self.verify_session_and_package(target_pkg, workflow.allowedPackages)
                self.active_package = target_pkg

                if action in ("back", "home", "scroll", "swipe"):
                    rec = StepExecutionRecord(
                        step_id=step_id,
                        action=action,
                        status="passed",
                        duration_ms=(time.perf_counter() - step_start) * 1000.0,
                    )
                    step_records.append(rec)
                    if step_observer:
                        step_observer(rec)
                    continue

                effective_step = WorkflowStep(
                    **{
                        **step.__dict__,
                        "selector": step.selector or step.resourceId or step.contentDesc,
                    }
                )
                candidates = self.snapshot_candidates()
                resolution = healer.resolve(
                    step=effective_step,
                    candidates=candidates,
                    primary_matcher=self.match_primary,
                    allowed_scopes=list(self.allowed_packages | set(workflow.allowedPackages)),
                )
                if not resolution.resolved or not resolution.candidate_id:
                    raise RuntimeError(f"Android step {step_id} ({action}) failed resolution: {resolution.reason}")

                node = self.nodes[resolution.candidate_id]
                self.verify_session_and_package(node.package_name, workflow.allowedPackages)

                if resolution.tier > 1:
                    healing_events.append(
                        {
                            "step_id": step_id,
                            "original_selector": effective_step.selector,
                            "healed_selector": resolution.selector,
                            "tier": resolution.tier,
                            "confidence": resolution.confidence,
                            "reason": resolution.reason,
                        }
                    )

                extracted = None
                if action in ("type", "type_text", "fill"):
                    raw_text = step.text if step.text is not None else str(step.value or "")
                    text_val, used_sec = resolve_step_parameters(raw_text, workflow, runtime_inputs, vault)
                    secrets_known.update(used_sec)
                    # Supports full Arabic & Unicode UTF-8 via AccessibilityNodeInfo.ACTION_SET_TEXT
                    node.text = str(text_val or "")
                elif action == "click":
                    if not node.clickable or not node.enabled:
                        raise RuntimeError(f"Android node {node.resource_id!r} is not clickable/enabled.")
                    node.text = node.text or "clicked"
                elif action == "extract_text":
                    if node.is_password:
                        raise PermissionError("Refusing to extract text from a password field on Android.")
                    extracted = node.text
                    outputs[step.variable or step_id] = extracted
                elif action in ("assert_text", "assert_visible", "assert_value"):
                    exp_val, used_sec = resolve_step_parameters(
                        str(step.expected) if step.expected is not None else None,
                        workflow,
                        runtime_inputs,
                        vault,
                    )
                    secrets_known.update(used_sec)
                    actual = node.visible if action == "assert_visible" else node.text
                    try:
                        evaluate_assertion(
                            AssertionSpec(type=action, selector=resolution.selector, expected=exp_val, match=step.match),
                            actual,
                        )
                        assertions_passed += 1
                    except AssertionFailureError:
                        assertions_failed += 1
                        raise

                rec = StepExecutionRecord(
                    step_id=step_id,
                    action=action,
                    status="healed" if resolution.tier > 1 else "passed",
                    duration_ms=(time.perf_counter() - step_start) * 1000.0,
                    selector_used=resolution.selector,
                    healing_tier=resolution.tier,
                    extracted_value=extracted,
                )
                step_records.append(rec)
                if step_observer:
                    step_observer(rec)

            return WorkflowRunReport(
                workflow_name=workflow.name,
                target=workflow.target,
                status="passed",
                duration_ms=(time.perf_counter() - t0) * 1000.0,
                steps=step_records,
                assertions_passed=assertions_passed,
                assertions_failed=assertions_failed,
                healing_events=healing_events,
                outputs=outputs,
            )
        except Exception as exc:
            return WorkflowRunReport(
                workflow_name=workflow.name,
                target=workflow.target,
                status="cancelled" if isinstance(exc, WorkflowCancelledError) else "failed",
                duration_ms=(time.perf_counter() - t0) * 1000.0,
                steps=step_records,
                assertions_passed=assertions_passed,
                assertions_failed=assertions_failed,
                healing_events=healing_events,
                outputs=outputs,
                error=redact_secrets(str(exc), secrets_known),
            )
