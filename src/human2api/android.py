"""Android Companion Client & ADB Loopback Bridge with session TTL, package allowlisting, and Unicode support."""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
import urllib.error
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

    def perform_node_action(self, node: AndroidNode, action: str, text: Optional[str] = None) -> Any:
        """Legacy in-memory adapter action hook. Live adapters send it to Android."""
        if action in ("type", "type_text", "fill"):
            node.text = str(text or "")
            return node.text
        if action == "click":
            if not node.clickable or not node.enabled:
                raise RuntimeError(f"Android node {node.resource_id!r} is not clickable/enabled.")
            return True
        if action in ("scroll", "scroll_forward"):
            if not node.scrollable:
                raise RuntimeError("Android node is not scrollable")
            return True
        if action == "extract_text":
            if node.is_password:
                raise PermissionError("Cannot extract a sensitive Android field")
            return node.text
        raise RuntimeError(f"Unsupported Android action: {action}")

    def perform_global_action(self, action: str) -> None:
        """Legacy in-memory adapter hook. The live adapter uses the device bridge."""
        if action not in ("back", "home"):
            raise RuntimeError(f"Unsupported global Android action: {action}")

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

                if action in ("back", "home"):
                    self.perform_global_action(action)
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
                    self.perform_node_action(node, action, str(text_val or ""))
                elif action in ("click", "scroll", "scroll_forward"):
                    self.perform_node_action(node, action)
                elif action == "extract_text":
                    extracted = self.perform_node_action(node, action)
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

            for aspec in workflow.assertions:
                cancel_token.check()
                wanted, used_sec = resolve_step_parameters(
                    str(aspec.expected) if aspec.expected is not None else None,
                    workflow, runtime_inputs, vault,
                )
                secrets_known.update(used_sec)
                self.snapshot_candidates()  # live bridge refresh, not stale memory
                matched = self.match_primary(aspec.selector or "")
                if len(matched) != 1:
                    assertions_failed += 1
                    raise AssertionFailureError("Android post-assertion selector not found or ambiguous")
                node = self.nodes[matched[0].candidate_id]
                if node.is_password:
                    raise PermissionError("Sensitive Android fields cannot be asserted")
                actual = node.visible if aspec.type == "assert_visible" else node.text
                try:
                    evaluate_assertion(
                        AssertionSpec(type=aspec.type, selector=aspec.selector, expected=wanted, match=aspec.match),
                        actual,
                    )
                    assertions_passed += 1
                except AssertionFailureError:
                    assertions_failed += 1
                    raise

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


class LiveAndroidCompanionClient(AndroidCompanionClient):
    """Real USB/ADB Android companion client; never falls back to the in-memory mock."""

    def __init__(self, token: Optional[str] = None, port: int = DEFAULT_COMPANION_PORT) -> None:
        super().__init__(port=port, nodes=[], consent_granted=True)
        self.bridge_token = (token or os.environ.get("H2A_ANDROID_TOKEN") or "").strip()
        if not self.bridge_token:
            raise PermissionError(
                "No Android pairing code. Enable the companion Accessibility Service, "
                "approve a 5-minute session on the phone, and use 'h2a android run'."
            )

    @staticmethod
    def forward_adb_port(port: int = DEFAULT_COMPANION_PORT, serial: Optional[str] = None) -> str:
        installed, connected, explanation = AndroidCompanionClient.probe_adb_devices()
        if not installed:
            raise RuntimeError("ADB is unavailable: " + explanation + ". Install Android SDK Platform Tools.")
        if serial and serial not in connected:
            raise RuntimeError(f"ADB device {serial!r} is not authorized/connected. Connected devices: {connected}")
        if not serial and len(connected) != 1:
            raise RuntimeError(f"Exactly one authorized Android device is needed, or pass --serial. Devices: {connected}")
        selected = serial or connected[0]
        proc = subprocess.run(
            ["adb", "-s", selected, "forward", f"tcp:{int(port)}", f"tcp:{DEFAULT_COMPANION_PORT}"],
            capture_output=True, text=True, timeout=12,
        )
        if proc.returncode != 0:
            raise RuntimeError("Failed to forward Android port: " + proc.stderr.strip())
        return selected

    def _request(self, path: str, payload: Optional[dict] = None, token_required: bool = True) -> dict:
        if self.port < 1 or self.port > 65535:
            raise ValueError("Invalid local Android bridge port")
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Accept": "application/json"}
        if token_required:
            headers["X-H2A-Token"] = self.bridge_token
        if data is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=data, headers=headers,
            method="POST" if payload is not None else "GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                raw = response.read(512 * 1024 + 1)
                if len(raw) > 512 * 1024:
                    raise RuntimeError("Android bridge response unexpectedly large")
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise PermissionError(
                f"Android bridge refused the request (HTTP {exc.code}). "
                "Check the phone's consent timer, package allowlist and pairing code."
            ) from exc
        except (OSError, urllib.error.URLError) as exc:
            raise ConnectionError(
                "Could not reach Android Companion on the forwarded USB port. "
                "Check USB debugging, 'adb devices', Accessibility Service and ADB forwarding."
            ) from exc

    def _refresh_remote_nodes(self) -> None:
        response = self._request("/nodes")
        if response.get("status") != "ok":
            raise RuntimeError("Android Companion did not return an approved UI tree")
        nodes = response.get("nodes")
        if not isinstance(nodes, list) or len(nodes) > 256:
            raise RuntimeError("Android Companion sent an invalid UI tree")
        self.nodes.clear()
        self.active_package = str(response.get("package_name") or "")
        for item in nodes:
            if item.get("is_password") or item.get("package_name") != self.active_package:
                continue
            if not isinstance(item.get("node_id"), str):
                continue
            self.register_node(AndroidNode(
                node_id=item["node_id"], resource_id=str(item.get("resource_id") or ""),
                text=str(item.get("text") or ""), content_desc=str(item.get("content_desc") or ""),
                class_name=str(item.get("class_name") or ""), package_name=self.active_package,
                clickable=bool(item.get("clickable")), editable=bool(item.get("editable")),
                scrollable=bool(item.get("scrollable")), enabled=bool(item.get("enabled")),
                visible=bool(item.get("visible")), is_password=False,
            ))

    def snapshot_candidates(self) -> List[UIElementCandidate]:
        self._refresh_remote_nodes()
        return super().snapshot_candidates()

    def perform_node_action(self, node: AndroidNode, action: str, text: Optional[str] = None) -> Any:
        if action == "extract_text":
            return super().perform_node_action(node, action, text)
        response = self._request("/action", {
            "node_id": node.node_id, "resource_id": node.resource_id,
            "class_name": node.class_name, "content_desc": node.content_desc,
            "action": action, "text": str(text or ""),
        })
        if response.get("performed") is not True:
            raise RuntimeError("Android device rejected or could not perform the action")
        if action in ("type", "type_text", "fill"):
            node.text = str(text or "")
        return True

    def perform_global_action(self, action: str) -> None:
        response = self._request("/action", {"action": action})
        if response.get("performed") is not True:
            raise RuntimeError("Android device refused the global action")

    def trigger_stop(self) -> None:
        super().trigger_stop()
        try:
            self._request("/stop", {}, token_required=False)
        except (OSError, RuntimeError, PermissionError):
            pass
