"""Optimistic-concurrency workflow editing with private revision backups."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import Any

from .models import WorkflowError, validate_workflow, workflow_file, save_workflow, WRITE_ACTIONS


class EditConflict(WorkflowError):
    """The file has changed since it was opened; never overwrite it silently."""


def revision(path: Path) -> str:
    if path.is_symlink():
        raise WorkflowError("workflow cannot be a symlink")
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "new"


def inspect_definition(workflow: dict[str, Any]) -> dict[str, Any]:
    validate_workflow(workflow)
    writes = [i for i, step in enumerate(workflow["steps"], 1) if step["action"] in WRITE_ACTIONS]
    warnings = []
    if writes:
        warnings.append("This workflow changes application state; run approval is required.")
    if not any(step["action"] in {"assert_text", "ui_assert_text", "assert_image"} for step in workflow["steps"]):
        warnings.append("No result assertion is defined. Add one before using this on important data.")
    if workflow.get("target", "browser") == "desktop" and any("x" in step for step in workflow["steps"]):
        warnings.append("Coordinate steps depend on window position and display scaling.")
    return {"valid": True, "executed": False, "stepCount": len(workflow["steps"]), "writeSteps": writes,
            "requiredInputs": list(workflow.get("inputs", {})), "warnings": warnings}


def save_revision(directory: Path, name: str, workflow: dict[str, Any], expected: str) -> str:
    validate_workflow(workflow)
    if workflow["name"] != name:
        raise WorkflowError("name differs from route")
    path = workflow_file(directory, name)
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / (name + ".edit-lock")
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise EditConflict("workflow is being edited; retry after reloading") from exc
    try:
        os.close(fd)
        current = revision(path)
        if expected != current:
            raise EditConflict("workflow changed since loading; reload before saving")
        if current != "new":
            backup_dir = directory.parent / ".h2a" / "revisions" / name
            backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            dest = backup_dir / (current + ".json")
            if not dest.exists():
                fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(path.read_bytes())
        save_workflow(path, workflow)
        return revision(path)
    finally:
        lock.unlink(missing_ok=True)
