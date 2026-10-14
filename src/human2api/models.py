"""Data models, schema validation, and backward-compatible migration for Human2API workflows."""

from __future__ import annotations

import copy
import json
import pathlib
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Union

SUPPORTED_SCHEMA_VERSIONS = {"0.1", "0.2", "0.3", "0.4", "0.5", "1.0"}
CURRENT_SCHEMA_VERSION = "0.5"

SUPPORTED_TARGETS = {
    "browser",
    "web",
    "desktop",
    "windows-uia",
    "macos-ax",
    "linux-atspi",
    "android",
    "android-companion",
}

SUPPORTED_ACTIONS = {
    "goto",
    "navigate",
    "click",
    "double_click",
    "type",
    "type_text",
    "fill",
    "select",
    "scroll",
    "wait",
    "wait_for_selector",
    "switch_tab",
    "open_tab",
    "close_tab",
    "switch_frame",
    "upload_file",
    "download_file",
    "extract_text",
    "assert_text",
    "assert_visible",
    "assert_url",
    "assert_value",
    "focus_window",
    "resize_window",
    "press_key",
    "back",
    "home",
    "swipe",
}

WRITE_CLASS_ACTIONS = {
    "click",
    "double_click",
    "type",
    "type_text",
    "fill",
    "select",
    "upload_file",
    "press_key",
    "swipe",
}

SECRET_REF_PATTERN = re.compile(r"\$\{\s*(secret|input)\s*:\s*([a-zA-Z0-9_.-]+)\s*\}")
LEGACY_VAR_PATTERN = re.compile(r"\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}")


@dataclass
class SelectorCandidate:
    strategy: str
    value: str
    role: Optional[str] = None
    name: Optional[str] = None
    confidence: float = 0.9

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"strategy": self.strategy, "value": self.value}
        if self.role:
            out["role"] = self.role
        if self.name:
            out["name"] = self.name
        if self.confidence is not None:
            out["confidence"] = round(float(self.confidence), 4)
        return out

    @classmethod
    def from_raw(cls, raw: Union[str, Dict[str, Any], "SelectorCandidate"]) -> "SelectorCandidate":
        if isinstance(raw, SelectorCandidate):
            return raw
        if isinstance(raw, str):
            strategy = "xpath" if raw.startswith("//") or raw.startswith("(//") else "css"
            return cls(strategy=strategy, value=raw)
        if isinstance(raw, dict):
            return cls(
                strategy=str(raw.get("strategy", "css")),
                value=str(raw.get("value", "")),
                role=raw.get("role"),
                name=raw.get("name"),
                confidence=float(raw.get("confidence", 0.9)),
            )
        raise ValueError(f"Invalid selector candidate: {raw!r}")


@dataclass
class InputSpec:
    type: str = "string"
    description: str = ""
    required: bool = True
    sensitive: bool = False
    default: Any = None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "type": self.type,
            "required": self.required,
            "sensitive": self.sensitive or self.type == "secret",
        }
        if self.description:
            out["description"] = self.description
        if self.default is not None and not out["sensitive"]:
            out["default"] = self.default
        return out

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InputSpec":
        t = str(data.get("type", "string"))
        sensitive = bool(data.get("sensitive", False) or t == "secret")
        return cls(
            type=t,
            description=str(data.get("description", "")),
            required=bool(data.get("required", True)),
            sensitive=sensitive,
            default=None if sensitive else data.get("default"),
        )


@dataclass
class AssertionSpec:
    type: str
    selector: Optional[str] = None
    expected: Any = None
    match: str = "contains"
    timeoutMs: int = 5000

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "type": self.type,
            "match": self.match,
            "timeoutMs": self.timeoutMs,
        }
        if self.selector is not None:
            out["selector"] = self.selector
        if self.expected is not None:
            out["expected"] = self.expected
        return out

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AssertionSpec":
        return cls(
            type=str(data["type"]),
            selector=data.get("selector"),
            expected=data.get("expected"),
            match=str(data.get("match", "contains")),
            timeoutMs=int(data.get("timeoutMs", 5000)),
        )


@dataclass
class HealingConfig:
    enabled: bool = True
    maxTier: int = 3
    aiConsent: bool = False
    aiProvider: str = "none"
    minSemanticConfidence: float = 0.72

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "maxTier": self.maxTier,
            "aiConsent": self.aiConsent,
            "aiProvider": self.aiProvider,
            "minSemanticConfidence": self.minSemanticConfidence,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "HealingConfig":
        if not data:
            return cls()
        return cls(
            enabled=bool(data.get("enabled", True)),
            maxTier=int(data.get("maxTier", 3)),
            aiConsent=bool(data.get("aiConsent", False)),
            aiProvider=str(data.get("aiProvider", "none")),
            minSemanticConfidence=float(data.get("minSemanticConfidence", 0.72)),
        )


@dataclass
class WorkflowStep:
    action: str
    id: Optional[str] = None
    selector: Optional[str] = None
    fallbackSelectors: List[Union[str, SelectorCandidate]] = field(default_factory=list)
    url: Optional[str] = None
    text: Optional[str] = None
    value: Any = None
    variable: Optional[str] = None
    sensitive: bool = False
    idempotent: bool = True
    isWriteAction: bool = False
    framePath: List[str] = field(default_factory=list)
    tabIndex: Optional[int] = None
    tabTitle: Optional[str] = None
    filePath: Optional[str] = None
    downloadName: Optional[str] = None
    role: Optional[str] = None
    name: Optional[str] = None
    automationId: Optional[str] = None
    windowTitle: Optional[str] = None
    packageName: Optional[str] = None
    resourceId: Optional[str] = None
    contentDesc: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None
    deltaX: float = 0
    deltaY: float = 300
    timeoutMs: int = 10000
    retries: int = 0
    retryDelayMs: int = 250
    expected: Any = None
    match: str = "contains"

    def normalized_fallbacks(self) -> List[SelectorCandidate]:
        return [SelectorCandidate.from_raw(item) for item in self.fallbackSelectors]

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"action": self.action}
        for key in (
            "id",
            "selector",
            "url",
            "text",
            "value",
            "variable",
            "tabIndex",
            "tabTitle",
            "filePath",
            "downloadName",
            "role",
            "name",
            "automationId",
            "windowTitle",
            "packageName",
            "resourceId",
            "contentDesc",
            "x",
            "y",
            "expected",
        ):
            val = getattr(self, key)
            if val is not None:
                out[key] = val
        if self.fallbackSelectors:
            out["fallbackSelectors"] = [
                item.to_dict() if isinstance(item, SelectorCandidate) else item
                for item in self.fallbackSelectors
            ]
        if self.framePath:
            out["framePath"] = list(self.framePath)
        if self.sensitive:
            out["sensitive"] = True
        if not self.idempotent:
            out["idempotent"] = False
        if self.isWriteAction:
            out["isWriteAction"] = True
        if self.action == "scroll":
            out["deltaX"] = self.deltaX
            out["deltaY"] = self.deltaY
        if self.timeoutMs != 10000:
            out["timeoutMs"] = self.timeoutMs
        if self.retries > 0:
            out["retries"] = self.retries
            out["retryDelayMs"] = self.retryDelayMs
        if self.expected is not None:
            out["match"] = self.match
        return out

    @classmethod
    def from_dict(cls, raw: Dict[str, Any], index: int = 0) -> "WorkflowStep":
        data = copy.deepcopy(raw)
        action = str(data.get("action") or data.get("type") or "").strip()
        if action == "input":
            action = "type"
        if action not in SUPPORTED_ACTIONS:
            raise ValueError(f"Unsupported step action at index {index}: {action!r}")

        is_write = bool(data.get("isWriteAction", False))
        idempotent = bool(data.get("idempotent", True))
        if action in ("type", "type_text", "fill", "upload_file"):
            # Typing/uploading into forms or submitting buttons can mutate state
            if "isWriteAction" not in data and data.get("submit"):
                is_write = True
                idempotent = False

        fallbacks_raw = data.get("fallbackSelectors") or data.get("fallbacks") or []
        fallbacks: List[Union[str, SelectorCandidate]] = []
        for f in fallbacks_raw:
            if isinstance(f, dict):
                fallbacks.append(SelectorCandidate.from_raw(f))
            elif isinstance(f, str):
                fallbacks.append(f)

        text_val = data.get("text")
        if isinstance(text_val, str):
            # Migrate legacy {{VAR}} to ${input:VAR}
            text_val = LEGACY_VAR_PATTERN.sub(r"${input:\1}", text_val)

        return cls(
            action=action,
            id=data.get("id") or f"step_{index + 1}",
            selector=data.get("selector"),
            fallbackSelectors=fallbacks,
            url=data.get("url"),
            text=text_val,
            value=data.get("value"),
            variable=data.get("variable"),
            sensitive=bool(data.get("sensitive", False)),
            idempotent=idempotent,
            isWriteAction=is_write,
            framePath=list(data.get("framePath") or []),
            tabIndex=data.get("tabIndex"),
            tabTitle=data.get("tabTitle"),
            filePath=data.get("filePath"),
            downloadName=data.get("downloadName"),
            role=data.get("role"),
            name=data.get("name"),
            automationId=data.get("automationId") or data.get("element_id"),
            windowTitle=data.get("windowTitle"),
            packageName=data.get("packageName"),
            resourceId=data.get("resourceId"),
            contentDesc=data.get("contentDesc"),
            x=data.get("x"),
            y=data.get("y"),
            deltaX=float(data.get("deltaX", 0)),
            deltaY=float(data.get("deltaY", 300)),
            timeoutMs=int(data.get("timeoutMs", 10000)),
            retries=int(data.get("retries", 0)),
            retryDelayMs=int(data.get("retryDelayMs", 250)),
            expected=data.get("expected"),
            match=str(data.get("match", "contains")),
        )


@dataclass
class Workflow:
    name: str
    target: str
    steps: List[WorkflowStep]
    schemaVersion: str = CURRENT_SCHEMA_VERSION
    id: Optional[str] = None
    description: str = ""
    version: str = "1.0.0"
    mode: str = "read"
    allowedHosts: List[str] = field(default_factory=list)
    allowedApps: List[str] = field(default_factory=list)
    allowedPackages: List[str] = field(default_factory=list)
    networkPolicy: str = "strict"
    inputs: Dict[str, InputSpec] = field(default_factory=dict)
    assertions: List[AssertionSpec] = field(default_factory=list)
    healing: HealingConfig = field(default_factory=HealingConfig)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("Workflow 'name' cannot be empty.")
        if self.target not in SUPPORTED_TARGETS:
            raise ValueError(f"Unsupported workflow target: {self.target!r}")
        if self.schemaVersion not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(f"Unsupported schemaVersion: {self.schemaVersion!r}")
        if not self.steps:
            raise ValueError("Workflow must contain at least one step.")
        if self.networkPolicy not in ("strict", "navigation-only", "open"):
            raise ValueError(f"Invalid networkPolicy: {self.networkPolicy!r}")
        if self.mode not in ("read", "write"):
            raise ValueError(f"Invalid mode: {self.mode!r}")

    def requires_write_approval(self) -> bool:
        if self.mode == "write":
            return True
        return any(step.isWriteAction or not step.idempotent for step in self.steps)

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "schemaVersion": self.schemaVersion,
            "name": self.name,
            "version": self.version,
            "target": self.target,
            "mode": self.mode,
            "networkPolicy": self.networkPolicy,
            "allowedHosts": list(self.allowedHosts),
            "allowedApps": list(self.allowedApps),
            "allowedPackages": list(self.allowedPackages),
            "inputs": {k: v.to_dict() for k, v in self.inputs.items()},
            "steps": [s.to_dict() for s in self.steps],
            "assertions": [a.to_dict() for a in self.assertions],
            "healing": self.healing.to_dict(),
        }
        if self.id:
            out["id"] = self.id
        if self.description:
            out["description"] = self.description
        if self.metadata:
            out["metadata"] = dict(self.metadata)
        return out

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any], migrate: bool = True) -> "Workflow":
        if not isinstance(raw, dict):
            raise ValueError("Workflow definition must be a JSON object.")
        data = migrate_workflow_dict(raw) if migrate else copy.deepcopy(raw)
        inputs = {
            k: InputSpec.from_dict(v) if isinstance(v, dict) else InputSpec(type=str(v))
            for k, v in (data.get("inputs") or {}).items()
        }
        steps = [
            s if isinstance(s, WorkflowStep) else WorkflowStep.from_dict(s, idx)
            for idx, s in enumerate(data.get("steps") or [])
        ]
        assertions = [
            a if isinstance(a, AssertionSpec) else AssertionSpec.from_dict(a)
            for a in (data.get("assertions") or [])
        ]
        return cls(
            schemaVersion=str(data.get("schemaVersion", CURRENT_SCHEMA_VERSION)),
            id=data.get("id"),
            name=str(data.get("name", "")).strip(),
            description=str(data.get("description", "")),
            version=str(data.get("version", "1.0.0")),
            target=str(data.get("target", "browser")),
            mode=str(data.get("mode", "read")),
            allowedHosts=list(data.get("allowedHosts") or []),
            allowedApps=list(data.get("allowedApps") or []),
            allowedPackages=list(data.get("allowedPackages") or []),
            networkPolicy=str(data.get("networkPolicy", "strict")),
            inputs=inputs,
            steps=steps,
            assertions=assertions,
            healing=HealingConfig.from_dict(data.get("healing")),
            metadata=dict(data.get("metadata") or {}),
        )

    @classmethod
    def load(cls, path: Union[str, pathlib.Path]) -> "Workflow":
        p = pathlib.Path(path)
        raw = json.loads(p.read_text(encoding="utf-8"))
        return cls.from_dict(raw)

    def save(self, path: Union[str, pathlib.Path]) -> pathlib.Path:
        p = pathlib.Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_json(indent=2) + "\n", encoding="utf-8")
        return p


def migrate_workflow_dict(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Safely migrate legacy workflow dictionaries (v0.1 - v0.4) to v0.5 without losing fields."""
    data = copy.deepcopy(raw)
    ver = str(data.get("schemaVersion", "0.3"))
    if ver not in SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError(f"Unsupported workflow schemaVersion: {ver!r}")
    data.setdefault("schemaVersion", CURRENT_SCHEMA_VERSION)
    if "platform" in data and "target" not in data:
        data["target"] = data.pop("platform")
    data.setdefault("target", "browser")
    data.setdefault("version", "1.0.0")
    data.setdefault("mode", "write" if data.get("requiresWrite") else "read")
    data.pop("requiresWrite", None)
    data.setdefault("networkPolicy", "strict")
    data.setdefault("allowedHosts", [])
    data.setdefault("allowedApps", [])
    data.setdefault("allowedPackages", [])
    data.setdefault("inputs", {})
    data.setdefault("assertions", [])
    data.setdefault("healing", {"enabled": True, "maxTier": 3, "aiConsent": False, "aiProvider": "none"})
    return data
