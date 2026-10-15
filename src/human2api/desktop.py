"""Desktop Automation Engine for Windows UIA, macOS AX, and Linux AT-SPI / GTK+ATK with Unicode & Arabic support."""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from human2api.contracts import StepExecutionRecord, WorkflowRunReport, redact_secrets
from human2api.desktop_access import (
    DesktopAccessibleNode,
    check_macos_ax_permission,
    detect_linux_display_protocol,
    sys_platform_name,
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


class BaseDesktopAdapter:
    """Base adapter implementing Accessibility-first resolution, pre-action verification, window resize recalculation, and Unicode text entry."""

    target_name: str = "desktop"

    def __init__(self, initial_nodes: Optional[List[DesktopAccessibleNode]] = None) -> None:
        self.nodes: Dict[str, DesktopAccessibleNode] = {}
        self.active_window: str = ""
        self.window_geometry: Dict[str, Tuple[int, int, int, int]] = {}
        if initial_nodes:
            for n in initial_nodes:
                self.register_node(n)

    def register_node(self, node: DesktopAccessibleNode) -> None:
        self.nodes[node.node_id] = node
        if not self.active_window and node.window_title:
            self.active_window = node.window_title
        if node.window_title and node.window_title not in self.window_geometry:
            self.window_geometry[node.window_title] = (0, 0, 1024, 768)

    def snapshot_candidates(self) -> List[UIElementCandidate]:
        out: List[UIElementCandidate] = []
        for node in self.nodes.values():
            if self.active_window and node.window_title and node.window_title != self.active_window:
                continue
            out.append(node.to_candidate())
        return out

    def match_primary(self, selector: str) -> List[UIElementCandidate]:
        sel = (selector or "").strip()
        matches: List[UIElementCandidate] = []
        for node in self.nodes.values():
            if self.active_window and node.window_title and node.window_title != self.active_window:
                continue
            cand = node.to_candidate()
            if (
                cand.selector == sel
                or node.automation_id == sel
                or f'automationId="{node.automation_id}"' == sel
                or f"#{node.automation_id}" == sel
                or f'role={node.role.lower()}[name="{node.name}"]' == sel
            ):
                matches.append(cand)
        return matches

    def _is_window_or_app_allowed(self, window_title: str, app_name: str, allowed_apps: List[str]) -> bool:
        if not allowed_apps:
            return True
        allowed_norm = {a.lower().strip() for a in allowed_apps if a.strip()}
        wt_low = (window_title or "").lower()
        app_low = (app_name or "").lower()
        if app_low in allowed_norm or wt_low in allowed_norm:
            return True
        for allowed in allowed_norm:
            if allowed and (allowed in wt_low or allowed in app_low):
                return True
        for n in self.nodes.values():
            if n.window_title == window_title and n.app_name.lower() in allowed_norm:
                return True
        return False

    def candidate_scopes(self, allowed_apps: List[str]) -> List[str]:
        """Return allowed scopes for self-healing; native adapters already filter windows."""
        return allowed_apps

    def verify_element_before_action(self, node: DesktopAccessibleNode, step: WorkflowStep, allowed_apps: List[str]) -> None:
        """Verify element state, window focus, bounds integrity, and allowed application scope before mutating action."""
        if not node.visible or not node.enabled:
            raise RuntimeError(f"Desktop element {node.node_id!r} ({node.name!r}) is not visible or enabled.")
        if node.bounds[2] <= 0 or node.bounds[3] <= 0:
            raise RuntimeError(f"Desktop element {node.node_id!r} has invalid zero/negative bounds {node.bounds}.")
        if not self._is_window_or_app_allowed(node.window_title, node.app_name, allowed_apps):
            raise PermissionError(
                f"Application {node.app_name or node.window_title!r} is not in allowedApps={allowed_apps}."
            )

    def activate_window(self, title: str) -> None:
        """Switch the active window. Native adapters override to focus the real OS window."""
        self.active_window = title

    def resize_window(self, window_title: str, width: int, height: int) -> None:
        """Simulate or apply window resize and recalculate relative element bounds cleanly."""
        old_geom = self.window_geometry.get(window_title, (0, 0, 1024, 768))
        scale_x = max(0.25, width / max(1, old_geom[2]))
        scale_y = max(0.25, height / max(1, old_geom[3]))
        self.window_geometry[window_title] = (old_geom[0], old_geom[1], width, height)
        for node in self.nodes.values():
            if node.window_title == window_title:
                x, y, w, h = node.bounds
                node.bounds = (
                    int(round(x * scale_x)),
                    int(round(y * scale_y)),
                    max(8, int(round(w * scale_x))),
                    max(8, int(round(h * scale_y))),
                )

    def perform_node_action(self, node: DesktopAccessibleNode, action: str, text_val: Optional[str] = None) -> Any:
        node.focused = True
        if action in ("click", "double_click"):
            if node.role.lower() in ("checkbox", "switch"):
                node.value = "false" if node.value == "true" else "true"
            elif node.role.lower() == "button":
                node.value = "invoked"
            return node.value
        if action in ("type", "type_text", "fill"):
            node.value = str(text_val or "")
            return node.value
        if action == "select":
            node.value = str(text_val or "")
            return node.value
        if action == "extract_text":
            return node.value or node.name
        return None

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

                if step.windowTitle:
                    self.active_window = step.windowTitle

                if action == "focus_window":
                    if not step.windowTitle:
                        raise ValueError(f"Step {step_id} focus_window requires windowTitle.")
                    if not self._is_window_or_app_allowed(step.windowTitle, "", workflow.allowedApps):
                        raise PermissionError(f"Window {step.windowTitle!r} is not in allowedApps={workflow.allowedApps}.")
                    self.activate_window(step.windowTitle)
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

                if action == "resize_window":
                    win = step.windowTitle or self.active_window
                    w = int(step.x or 1280)
                    h = int(step.y or 800)
                    self.resize_window(win, w, h)
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

                candidates = self.snapshot_candidates()
                resolution = healer.resolve(
                    step=step,
                    candidates=candidates,
                    primary_matcher=self.match_primary,
                    allowed_scopes=self.candidate_scopes(workflow.allowedApps),
                    already_executed_write=False,
                )
                if not resolution.resolved or not resolution.candidate_id:
                    if "outside allowed scopes" in resolution.reason:
                        raise PermissionError(f"Target element is not in allowedApps: {resolution.reason}")
                    raise RuntimeError(f"Desktop step {step_id} ({action}) failed resolution: {resolution.reason}")

                node = self.nodes.get(resolution.candidate_id)
                if node is None:
                    raise RuntimeError(f"Resolved desktop node {resolution.candidate_id!r} no longer exists.")

                self.verify_element_before_action(node, step, workflow.allowedApps)

                if resolution.tier > 1:
                    healing_events.append(
                        {
                            "step_id": step_id,
                            "original_selector": step.selector or step.automationId,
                            "healed_selector": resolution.selector,
                            "tier": resolution.tier,
                            "confidence": resolution.confidence,
                            "reason": resolution.reason,
                        }
                    )

                extracted = None
                if action in ("type", "type_text", "fill", "select"):
                    raw_text = step.text if step.text is not None else str(step.value or "")
                    text_val, used_sec = resolve_step_parameters(raw_text, workflow, runtime_inputs, vault)
                    secrets_known.update(used_sec)
                    self.perform_node_action(node, action, text_val)
                elif action in ("assert_text", "assert_visible", "assert_value"):
                    exp_val, used_sec = resolve_step_parameters(
                        str(step.expected) if step.expected is not None else None,
                        workflow,
                        runtime_inputs,
                        vault,
                    )
                    secrets_known.update(used_sec)
                    actual = (
                        node.visible
                        if action == "assert_visible"
                        else (node.value if action == "assert_value" else (node.value or node.name))
                    )
                    try:
                        evaluate_assertion(
                            AssertionSpec(type=action, selector=resolution.selector, expected=exp_val, match=step.match),
                            actual,
                        )
                        assertions_passed += 1
                    except AssertionFailureError:
                        assertions_failed += 1
                        raise
                else:
                    extracted = self.perform_node_action(node, action)
                    if action == "extract_text" and extracted is not None:
                        outputs[step.variable or step_id] = extracted

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
                exp_val, used_sec = resolve_step_parameters(
                    str(aspec.expected) if aspec.expected is not None else None,
                    workflow,
                    runtime_inputs,
                    vault,
                )
                secrets_known.update(used_sec)
                matched = self.match_primary(aspec.selector or "")
                if not matched:
                    assertions_failed += 1
                    raise AssertionFailureError(f"Desktop post-assertion selector {aspec.selector!r} not found.")
                node = self.nodes[matched[0].candidate_id]
                actual = (
                    node.visible
                    if aspec.type == "assert_visible"
                    else (node.value if aspec.type == "assert_value" else (node.value or node.name))
                )
                try:
                    evaluate_assertion(
                        AssertionSpec(type=aspec.type, selector=aspec.selector, expected=exp_val, match=aspec.match),
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


class WindowsUIAAdapter(BaseDesktopAdapter):
    target_name = "windows-uia"

    def __init__(self, initial_nodes: Optional[List[DesktopAccessibleNode]] = None) -> None:
        super().__init__(initial_nodes)
        self._bridge = None
        self._live = initial_nodes is None
        self._allowed_apps: List[str] = []
        if self._live:
            from human2api.windows_live import WindowsUIABridge
            self._bridge = WindowsUIABridge()

    def execute_workflow(self, workflow, runtime_inputs, vault, secrets_known, cancel_token, **kwargs):
        self._allowed_apps = list(workflow.allowedApps)
        return super().execute_workflow(workflow, runtime_inputs, vault, secrets_known, cancel_token, **kwargs)

    def snapshot_candidates(self) -> List[UIElementCandidate]:
        if self._live:
            assert self._bridge is not None
            nodes = self._bridge.snapshot(self._allowed_apps, self.active_window)
            self.nodes = {n.node_id: n for n in nodes}
        return super().snapshot_candidates()

    def candidate_scopes(self, allowed_apps: List[str]) -> List[str]:
        if self._live:
            # The native bridge admits only app windows matching the explicit allowlist.
            # Use the resolved full window title for the self-healing exact-scope check.
            return sorted({n.window_title for n in self.nodes.values()})
        return allowed_apps

    def match_primary(self, selector: str) -> List[UIElementCandidate]:
        if self._live:
            self.snapshot_candidates()  # Refresh changed native labels before post-condition checks.
        return super().match_primary(selector)

    def activate_window(self, title: str) -> None:
        if self._live:
            assert self._bridge is not None
            self.active_window = self._bridge.focus_window(title, self._allowed_apps)
        else:
            self.active_window = title

    def resize_window(self, window_title: str, width: int, height: int) -> None:
        if self._live:
            assert self._bridge is not None
            self._bridge.resize_window(window_title, width, height)
            self.snapshot_candidates()
        else:
            super().resize_window(window_title, width, height)

    def perform_node_action(self, node: DesktopAccessibleNode, action: str, text_val: Optional[str] = None) -> Any:
        if not self._live:
            return super().perform_node_action(node, action, text_val)
        assert self._bridge is not None
        result = self._bridge.action(node, action, text_val)
        node.value = str(result or "")
        return result


class MacOSAXAdapter(BaseDesktopAdapter):
    target_name = "macos-ax"

    def __init__(self, initial_nodes: Optional[List[DesktopAccessibleNode]] = None, enforce_os_trust: bool = False) -> None:
        super().__init__(initial_nodes)
        self.enforce_os_trust = enforce_os_trust

    def verify_element_before_action(self, node: DesktopAccessibleNode, step: WorkflowStep, allowed_apps: List[str]) -> None:
        if self.enforce_os_trust:
            trusted, reason = check_macos_ax_permission()
            if not trusted:
                raise PermissionError(reason)
        super().verify_element_before_action(node, step, allowed_apps)


class LinuxATSPIAdapter(BaseDesktopAdapter):
    target_name = "linux-atspi"

    def session_capabilities(self) -> Dict[str, Any]:
        return detect_linux_display_protocol()


def get_desktop_adapter(target: str, initial_nodes: Optional[List[DesktopAccessibleNode]] = None) -> BaseDesktopAdapter:
    if target == "windows-uia" or (target == "desktop" and sys_platform_name() == "windows-uia"):
        return WindowsUIAAdapter(initial_nodes)
    if target == "macos-ax" or (target == "desktop" and sys_platform_name() == "macos-ax"):
        return MacOSAXAdapter(initial_nodes)
    return LinuxATSPIAdapter(initial_nodes)
