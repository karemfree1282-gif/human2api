"""Visual Workflow Editor CAS (Compare-And-Swap) operations: add, delete, reorder, parameterize steps without manual JSON editing."""

from __future__ import annotations

import copy
import hashlib
from typing import Any, Dict, List, Optional, Tuple

from human2api.models import AssertionSpec, InputSpec, Workflow, WorkflowStep


def compute_workflow_etag(workflow: Workflow) -> str:
    payload = workflow.to_json(indent=0).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


class VisualWorkflowEditor:
    """Provides safe, high-level mutations on Workflow objects for the Visual Studio UI without requiring manual JSON editing."""

    @staticmethod
    def add_step(workflow: Workflow, step_dict: Dict[str, Any], position: Optional[int] = None) -> Workflow:
        data = workflow.to_dict()
        steps = list(data.get("steps", []))
        idx = len(steps) if position is None else max(0, min(int(position), len(steps)))
        new_step = WorkflowStep.from_dict(step_dict, index=idx).to_dict()
        steps.insert(idx, new_step)
        for i, s in enumerate(steps):
            s["id"] = f"step_{i + 1}"
        data["steps"] = steps
        return Workflow.from_dict(data)

    @staticmethod
    def delete_step(workflow: Workflow, index: int) -> Workflow:
        data = workflow.to_dict()
        steps = list(data.get("steps", []))
        if len(steps) <= 1:
            raise ValueError("Workflow must retain at least one step.")
        if index < 0 or index >= len(steps):
            raise IndexError(f"Step index {index} out of range.")
        steps.pop(index)
        for i, s in enumerate(steps):
            s["id"] = f"step_{i + 1}"
        data["steps"] = steps
        return Workflow.from_dict(data)

    @staticmethod
    def reorder_steps(workflow: Workflow, from_index: int, to_index: int) -> Workflow:
        data = workflow.to_dict()
        steps = list(data.get("steps", []))
        if from_index < 0 or from_index >= len(steps) or to_index < 0 or to_index >= len(steps):
            raise IndexError("Step reorder index out of range.")
        item = steps.pop(from_index)
        steps.insert(to_index, item)
        for i, s in enumerate(steps):
            s["id"] = f"step_{i + 1}"
        data["steps"] = steps
        return Workflow.from_dict(data)

    @staticmethod
    def set_input_parameter(
        workflow: Workflow,
        name: str,
        input_type: str = "string",
        description: str = "",
        required: bool = True,
        sensitive: bool = False,
        default: Any = None,
    ) -> Workflow:
        data = workflow.to_dict()
        inputs = dict(data.get("inputs") or {})
        spec = InputSpec(
            type=input_type,
            description=description,
            required=required,
            sensitive=sensitive or input_type == "secret",
            default=None if (sensitive or input_type == "secret") else default,
        )
        inputs[name.strip()] = spec.to_dict()
        data["inputs"] = inputs
        return Workflow.from_dict(data)

    @staticmethod
    def add_assertion(workflow: Workflow, assertion_dict: Dict[str, Any]) -> Workflow:
        data = workflow.to_dict()
        assertions = list(data.get("assertions") or [])
        assertions.append(AssertionSpec.from_dict(assertion_dict).to_dict())
        data["assertions"] = assertions
        return Workflow.from_dict(data)
