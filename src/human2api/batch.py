"""Sequential, fail-fast batch replay. Inputs stay in memory, not in reports."""
from __future__ import annotations
import csv
import json
from pathlib import Path
from typing import Any, Callable

from .models import WorkflowError, validate_inputs
from .runner import run_workflow


def read_rows(path: Path, workflow: dict[str, Any], *, limit: int = 1000) -> list[dict[str, Any]]:
    if path.stat().st_size > 8 * 1024 * 1024:
        raise WorkflowError("batch input file exceeds 8 MiB")
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".csv":
        import io
        rows = list(csv.DictReader(io.StringIO(text)))
        for row in rows:
            for key, spec in workflow.get("inputs", {}).items():
                if key not in row:
                    continue
                if spec.get("type") == "number":
                    try:
                        row[key] = float(row[key])
                    except (ValueError, TypeError) as exc:
                        raise WorkflowError("CSV number conversion failed") from exc
                elif spec.get("type") == "boolean":
                    if str(row[key]).lower() not in {"true", "false"}:
                        raise WorkflowError("CSV booleans must be true or false")
                    row[key] = str(row[key]).lower() == "true"
    elif path.suffix.lower() == ".jsonl":
        rows = [json.loads(x) for x in text.splitlines() if x.strip()]
    else:
        rows = json.loads(text)
    if not isinstance(rows, list) or not 1 <= len(rows) <= limit:
        raise WorkflowError(f"batch must have 1-{limit} rows")
    # Validate the entire input before making the first side effect.
    return [validate_inputs(workflow, row) for row in rows]


def run_batch(workflow: dict[str, Any], rows: list[dict[str, Any]], *, approve: bool = False,
              artifacts_dir: Path = Path("runs"), runner: Callable = run_workflow) -> dict[str, Any]:
    valid = [validate_inputs(workflow, row) for row in rows]
    if not valid or len(valid) > 1000:
        raise WorkflowError("batch must have 1-1000 rows")
    records = []
    for ordinal, inputs in enumerate(valid, 1):
        try:
            result = runner(workflow, inputs, approve_writes=approve, artifacts_dir=artifacts_dir)
            records.append({"row": ordinal, "ok": True, "runId": result["runId"]})
        except (WorkflowError, OSError) as exc:
            records.append({"row": ordinal, "ok": False, "errorType": type(exc).__name__})
            return {"ok": False, "completed": ordinal - 1, "total": len(valid), "runs": records,
                    "message": "Stopped at the first failed row; no automatic retry of side effects"}
    return {"ok": True, "completed": len(records), "total": len(valid), "runs": records}
