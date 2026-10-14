"""Privacy-Preserving Run History Journal, Task Scheduler, Device Leases, and HTTP Rate/Size Limits."""

from __future__ import annotations

import json
import os
import pathlib
import stat
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

from human2api.contracts import WorkflowRunReport, redact_secrets


class RunHistoryJournal:
    """Stores privacy-preserving execution metadata on disk without persisting raw inputs or secret outputs."""

    def __init__(self, journal_path: pathlib.Path, max_entries: int = 200) -> None:
        self.journal_path = pathlib.Path(journal_path)
        self.max_entries = max_entries
        self._lock = threading.Lock()

    def record_run(self, report: WorkflowRunReport, secret_values: Optional[Set[str]] = None) -> Dict[str, Any]:
        entry = {
            "run_id": f"run_{uuid.uuid4().hex[:12]}",
            "timestamp": time.time(),
            "workflow_name": report.workflow_name,
            "target": report.target,
            "status": report.status,
            "duration_ms": round(report.duration_ms, 2),
            "step_count": len(report.steps),
            "steps_passed": sum(1 for s in report.steps if s.status in ("passed", "healed")),
            "steps_healed": sum(1 for s in report.steps if s.status == "healed"),
            "assertions_passed": report.assertions_passed,
            "assertions_failed": report.assertions_failed,
            "error": redact_secrets(report.error, secret_values) if report.error else None,
        }
        with self._lock:
            entries = self.list_runs()
            entries.insert(0, entry)
            entries = entries[: self.max_entries]
            self.journal_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.journal_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            try:
                os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass
            tmp.replace(self.journal_path)
        return entry

    def list_runs(self, limit: int = 50) -> List[Dict[str, Any]]:
        if not self.journal_path.exists():
            return []
        try:
            data = json.loads(self.journal_path.read_text(encoding="utf-8"))
            return list(data[:limit]) if isinstance(data, list) else []
        except Exception:
            return []

    def clear(self) -> None:
        with self._lock:
            if self.journal_path.exists():
                self.journal_path.unlink()
