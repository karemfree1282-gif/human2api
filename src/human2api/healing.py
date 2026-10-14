"""4-Tier Self-Healing Engine for Human2API with strict safety and uniqueness verification."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from human2api.contracts import is_sensitive_field_name, redact_secrets
from human2api.models import HealingConfig, SelectorCandidate, WorkflowStep

INTERACTIVE_ROLES_BY_ACTION: Dict[str, Tuple[str, ...]] = {
    "click": ("button", "link", "menuitem", "tab", "checkbox", "radio", "switch", "option", "pushbutton"),
    "double_click": ("button", "link", "listitem", "treeitem", "cell"),
    "type": ("textbox", "searchbox", "combobox", "entry", "edit", "text", "textarea", "input"),
    "type_text": ("textbox", "searchbox", "combobox", "entry", "edit", "text", "textarea", "input"),
    "fill": ("textbox", "searchbox", "combobox", "entry", "edit", "text", "textarea", "input"),
    "select": ("combobox", "listbox", "select", "menuitem"),
    "upload_file": ("file", "button", "textbox", "input"),
}

PRIVILEGE_ESCALATION_KEYWORDS = {
    "grant_admin",
    "allow_all_permissions",
    "disable_security",
    "root_access",
    "sudo",
    "delete_account",
    "format_disk",
    "install_unknown_apps",
}


@dataclass
class UIElementCandidate:
    """Sanitized representation of a UI/DOM/Accessibility element for healing evaluation."""

    candidate_id: str
    selector: str
    role: str = ""
    name: str = ""
    automation_id: str = ""
    resource_id: str = ""
    content_desc: str = ""
    placeholder: str = ""
    tag_name: str = ""
    visible: bool = True
    enabled: bool = True
    is_password: bool = False
    host_or_package: str = ""
    context_landmark: str = ""

    def sanitized_metadata(self) -> Dict[str, Any]:
        """Return bounded metadata safe to share with an optional AI recovery provider."""
        safe_name = "" if self.is_password or is_sensitive_field_name(self.name) else self.name[:120]
        safe_placeholder = (
            "" if self.is_password or is_sensitive_field_name(self.placeholder) else self.placeholder[:120]
        )
        return {
            "candidate_id": self.candidate_id,
            "role": self.role,
            "name": redact_secrets(safe_name),
            "automation_id": self.automation_id[:80],
            "resource_id": self.resource_id[:80],
            "tag_name": self.tag_name[:32],
            "placeholder": redact_secrets(safe_placeholder),
            "context_landmark": self.context_landmark[:80],
            "visible": self.visible,
            "enabled": self.enabled,
        }


@dataclass
class HealingResolution:
    resolved: bool
    tier: int  # 1=primary, 2=fallback, 3=semantic, 4=ai_assisted, 0=failed
    selector: Optional[str] = None
    candidate_id: Optional[str] = None
    confidence: float = 0.0
    reason: str = ""


class SelfHealingEngine:
    """Multi-tier self-healing resolver with strict safety, scope, and idempotency guards."""

    def __init__(
        self,
        config: Optional[HealingConfig] = None,
        ai_advisor: Optional[Callable[[Dict[str, Any], List[Dict[str, Any]]], Optional[str]]] = None,
    ) -> None:
        self.config = config or HealingConfig()
        self.ai_advisor = ai_advisor

    @staticmethod
    def _normalize_text(val: Optional[str]) -> str:
        if not val:
            return ""
        return re.sub(r"\s+", " ", val.strip().lower())

    @classmethod
    def _similarity(cls, a: Optional[str], b: Optional[str]) -> float:
        na, nb = cls._normalize_text(a), cls._normalize_text(b)
        if not na or not nb:
            return 0.0
        if na == nb:
            return 1.0
        if na in nb or nb in na:
            return 0.88
        return difflib.SequenceMatcher(None, na, nb).ratio()

    @staticmethod
    def verify_candidate_safety(
        step: WorkflowStep,
        candidate: UIElementCandidate,
        allowed_scopes: Sequence[str],
        already_executed_write: bool = False,
    ) -> Tuple[bool, str]:
        """Verify that a proposed healing candidate meets all security & operational constraints."""
        if already_executed_write and (step.isWriteAction or not step.idempotent):
            return False, "Refusing to heal or re-execute a non-idempotent write action that may have already succeeded."
        if not candidate.visible or not candidate.enabled:
            return False, "Candidate element is hidden or disabled."
        if allowed_scopes and candidate.host_or_package:
            allowed_norm = {s.lower().strip() for s in allowed_scopes if s.strip()}
            loopback_group = {"127.0.0.1", "127.0.0.2", "localhost", "::1"}
            cand_scope = candidate.host_or_package.lower().strip()
            if not (
                cand_scope in allowed_norm
                or (cand_scope in loopback_group and (allowed_norm & loopback_group))
            ):
                return False, f"Candidate scope {candidate.host_or_package!r} is outside allowed scopes {sorted(allowed_norm)}."

        # Check privilege escalation keywords in candidate labels/ids
        combined_ident = " ".join(
            [
                candidate.name,
                candidate.automation_id,
                candidate.resource_id,
                candidate.content_desc,
                candidate.selector,
            ]
        ).lower()
        for kw in PRIVILEGE_ESCALATION_KEYWORDS:
            if kw in combined_ident and kw not in (step.selector or "").lower() and kw not in (step.name or "").lower():
                return False, f"Candidate triggers privilege escalation guard ({kw!r})."

        # Check role suitability for action
        expected_roles = INTERACTIVE_ROLES_BY_ACTION.get(step.action)
        if expected_roles and candidate.role:
            role_norm = candidate.role.lower().strip()
            if role_norm not in expected_roles and candidate.tag_name.lower() not in expected_roles:
                return (
                    False,
                    f"Candidate role {candidate.role!r} is incompatible with action {step.action!r}.",
                )
        return True, "verified"

    def resolve(
        self,
        step: WorkflowStep,
        candidates: List[UIElementCandidate],
        primary_matcher: Optional[Callable[[str], List[UIElementCandidate]]] = None,
        allowed_scopes: Sequence[str] = (),
        already_executed_write: bool = False,
    ) -> HealingResolution:
        """Execute 4-tier resolution:
        Tier 1: Primary selector
        Tier 2: Recorded fallback selectors
        Tier 3: Semantic accessibility/name/role/context match
        Tier 4: Consent-gated AI advisor returning strictly a candidate_id (never executable code)
        """
        if already_executed_write and (step.isWriteAction or not step.idempotent):
            return HealingResolution(
                resolved=False,
                tier=0,
                reason="Write action already dispatched; skipping self-healing retry to prevent duplicate write.",
            )

        def _match_selector(sel: str) -> List[UIElementCandidate]:
            if primary_matcher is not None:
                return primary_matcher(sel)
            return [c for c in candidates if c.selector == sel or c.automation_id == sel or c.resource_id == sel]

        last_safety_reason = ""
        # Tier 1: Primary selector
        if step.selector:
            matches = _match_selector(step.selector)
            if len(matches) == 1:
                ok, reason = self.verify_candidate_safety(step, matches[0], allowed_scopes, already_executed_write)
                if ok:
                    return HealingResolution(
                        resolved=True,
                        tier=1,
                        selector=matches[0].selector,
                        candidate_id=matches[0].candidate_id,
                        confidence=1.0,
                        reason="Resolved via primary selector (Tier 1).",
                    )
                last_safety_reason = reason
            elif len(matches) > 1:
                return HealingResolution(
                    resolved=False,
                    tier=0,
                    reason=f"Ambiguous primary selector {step.selector!r}: matched {len(matches)} elements.",
                )

        if not self.config.enabled:
            return HealingResolution(resolved=False, tier=0, reason="Primary selector failed and healing is disabled.")

        # Tier 2: Recorded fallback selectors
        if self.config.maxTier >= 2:
            for fb in step.normalized_fallbacks():
                matches = _match_selector(fb.value)
                if len(matches) == 1:
                    ok, reason = self.verify_candidate_safety(step, matches[0], allowed_scopes, already_executed_write)
                    if ok:
                        return HealingResolution(
                            resolved=True,
                            tier=2,
                            selector=matches[0].selector,
                            candidate_id=matches[0].candidate_id,
                            confidence=fb.confidence,
                            reason=f"Resolved via fallback selector {fb.strategy}={fb.value!r} (Tier 2).",
                        )

        # Tier 3: Semantic Accessibility / Name / Role / Context matching
        if self.config.maxTier >= 3 and candidates:
            scored: List[Tuple[float, UIElementCandidate]] = []
            target_name = step.name or ""
            target_role = (step.role or "").lower().strip()
            target_auto = step.automationId or step.resourceId or ""
            for cand in candidates:
                ok, _ = self.verify_candidate_safety(step, cand, allowed_scopes, already_executed_write)
                if not ok:
                    continue
                score = 0.0
                weights = 0.0
                if target_name:
                    name_sim = max(
                        self._similarity(target_name, cand.name),
                        self._similarity(target_name, cand.content_desc),
                        self._similarity(target_name, cand.placeholder),
                    )
                    score += name_sim * 0.55
                    weights += 0.55
                if target_role:
                    role_sim = 1.0 if cand.role.lower() == target_role else 0.0
                    score += role_sim * 0.25
                    weights += 0.25
                if target_auto:
                    auto_sim = max(
                        self._similarity(target_auto, cand.automation_id),
                        self._similarity(target_auto, cand.resource_id),
                        self._similarity(target_auto, cand.selector),
                    )
                    score += auto_sim * 0.20
                    weights += 0.20
                if weights > 0:
                    final_score = score / weights
                    if final_score >= self.config.minSemanticConfidence:
                        scored.append((final_score, cand))

            scored.sort(key=lambda item: item[0], reverse=True)
            if len(scored) == 1 or (
                len(scored) > 1 and (scored[0][0] - scored[1][0]) >= 0.08
            ):
                best_score, best_cand = scored[0]
                return HealingResolution(
                    resolved=True,
                    tier=3,
                    selector=best_cand.selector,
                    candidate_id=best_cand.candidate_id,
                    confidence=round(best_score, 4),
                    reason=f"Resolved via semantic accessibility match (Tier 3, confidence={best_score:.2f}).",
                )
            elif len(scored) > 1:
                return HealingResolution(
                    resolved=False,
                    tier=0,
                    reason=f"Ambiguous semantic candidates (top scores {scored[0][0]:.2f} vs {scored[1][0]:.2f}). Refusing unsafe guess.",
                )

        # Tier 4: Optional AI Advisor (strictly bounded, consent-gated, never executes code)
        if (
            self.config.maxTier >= 4
            and self.config.aiConsent
            and self.config.aiProvider in ("local", "remote")
            and self.ai_advisor is not None
            and candidates
        ):
            safe_candidates = [
                c for c in candidates if self.verify_candidate_safety(step, c, allowed_scopes, already_executed_write)[0]
            ]
            if safe_candidates:
                step_summary = {
                    "action": step.action,
                    "role": step.role or "",
                    "name": "" if step.sensitive or is_sensitive_field_name(step.name) else (step.name or ""),
                    "automationId": step.automationId or "",
                }
                sanitized_list = [c.sanitized_metadata() for c in safe_candidates[:25]]
                proposed_id = self.ai_advisor(step_summary, sanitized_list)
                if proposed_id and isinstance(proposed_id, str):
                    # Strictly reject anything that looks like code or script injection
                    if any(tok in proposed_id for tok in ("(", ")", ";", "eval", "exec", "javascript:", "<script")):
                        return HealingResolution(
                            resolved=False,
                            tier=0,
                            reason="AI advisor returned invalid/unsafe candidate identifier.",
                        )
                    matched_cands = [c for c in safe_candidates if c.candidate_id == proposed_id]
                    if len(matched_cands) == 1:
                        chosen = matched_cands[0]
                        ok, reason = self.verify_candidate_safety(
                            step, chosen, allowed_scopes, already_executed_write
                        )
                        if ok:
                            return HealingResolution(
                                resolved=True,
                                tier=4,
                                selector=chosen.selector,
                                candidate_id=chosen.candidate_id,
                                confidence=0.80,
                                reason="Resolved via consent-gated AI candidate selection (Tier 4).",
                            )

        return HealingResolution(
            resolved=False,
            tier=0,
            reason=last_safety_reason or f"Element could not be uniquely resolved across tiers 1..{self.config.maxTier}.",
        )
