"""Local opt-in recurring workflow scheduler, with no cloud or credential storage.

A schedule stores only a workflow name, an interval, an approved-write flag and
an optional absolute PATH to a locked-down data file, never its contents. The
scheduler must be explicitly started; reboot persistence is the OS user's job.
"""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .history import RunJournal
from .models import NAME_RE, WorkflowError, load_workflow, validate_inputs, workflow_file
from .runner import run_workflow

MAX_SCHEDULES = 64


def _private_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise WorkflowError("schedule input file must be a regular, non-symlink JSON file")
    if path.stat().st_size > 65536:
        raise WorkflowError("schedule input file exceeds 64 KiB")
    if os.name != "nt" and path.stat().st_mode & 0o077:
        raise WorkflowError("schedule input file must not be readable by group/others; chmod 600")


def _inputs(path: str | None, workflow: dict[str, Any]) -> dict[str, Any]:
    if path is None:
        return validate_inputs(workflow, {})
    p = Path(path)
    _private_file(p)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise WorkflowError("schedule input file is not valid JSON") from exc
    return validate_inputs(workflow, data)


class LocalScheduler:
    def __init__(self, directory: Path) -> None:
        self.workflows = Path(directory).resolve()
        self.metadata = self.workflows.parent / ".h2a"
        self.metadata.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.registry = self.metadata / "schedules.json"
        self.lock_file = self.metadata / "scheduler.lock"

    @contextmanager
    def _lock(self) -> Iterator[None]:
        # Only one scheduler process may mutate the registry at a time.
        fd = os.open(self.lock_file, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if os.name == "nt":
                import msvcrt
                os.write(fd, b" ")
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        except BlockingIOError as exc:
            raise WorkflowError("another scheduler process is already running") from exc
        finally:
            if os.name == "nt":
                try:
                    import msvcrt
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _load(self) -> list[dict[str, Any]]:
        if not self.registry.exists():
            return []
        if self.registry.is_symlink() or self.registry.stat().st_size > 64_000:
            raise WorkflowError("schedule registry is unsafe or too large")
        try:
            value = json.loads(self.registry.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise WorkflowError("schedule registry is corrupt") from exc
        if not isinstance(value, list) or len(value) > MAX_SCHEDULES:
            raise WorkflowError("schedule registry is malformed")
        return value

    def _save(self, entries: list[dict[str, Any]]) -> None:
        if len(entries) > MAX_SCHEDULES:
            raise WorkflowError("schedule limit reached")
        value = json.dumps(entries, ensure_ascii=False, indent=2) + "\n"
        path = self.registry.with_suffix(".tmp")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(value)
        os.replace(path, self.registry)

    def add(self, name: str, *, every_minutes: int, approve_writes: bool = False, data_file: Path | None = None) -> dict[str, Any]:
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            raise WorkflowError("invalid workflow name")
        if type(every_minutes) is not int or not 1 <= every_minutes <= 10080:
            raise WorkflowError("schedule frequency must be between 1 and 10080 minutes")
        workflow = load_workflow(workflow_file(self.workflows, name))
        if workflow.get("permissions", "write") == "write" and not approve_writes:
            raise WorkflowError("scheduled write workflows require explicit --approve")
        resolved = str(Path(data_file).expanduser().resolve()) if data_file is not None else None
        _inputs(resolved, workflow)
        current = int(time.time())
        entry = {"name": name, "everyMinutes": every_minutes, "nextRunAt": current + every_minutes * 60,
                 "dataFile": resolved, "approveWrites": approve_writes, "createdAt": current,
                 "lastRunAt": None, "lastState": None}
        with self._lock():
            entries = self._load()
            if any(e.get("name") == name for e in entries):
                raise WorkflowError("schedule already exists for this workflow; remove it before changing interval")
            entries.append(entry)
            self._save(entries)
        return entry

    def list(self) -> list[dict[str, Any]]:
        with self._lock():
            return self._load()

    def remove(self, name: str) -> None:
        with self._lock():
            entries = self._load()
            reduced = [item for item in entries if item.get("name") != name]
            if len(entries) == len(reduced):
                raise WorkflowError("schedule not found")
            self._save(reduced)

    def run_due(self, *, now: int | None = None) -> list[dict[str, Any]]:
        """Claim due jobs before executing them; never accidentally replay on failure."""
        now = int(time.time()) if now is None else now
        with self._lock():
            entries = self._load()
            due: list[dict[str, Any]] = []
            for entry in entries:
                if entry["nextRunAt"] <= now:
                    due.append(entry.copy())
                    interval = entry["everyMinutes"] * 60
                    entry["nextRunAt"] += ((now - entry["nextRunAt"]) // interval + 1) * interval
                    entry["lastRunAt"] = now
                    entry["lastState"] = "starting"
            if due:
                self._save(entries)
        outcomes: list[dict[str, Any]] = []
        for entry in due:
            run_id = os.urandom(12).hex()
            status = "failed"
            started = time.monotonic()
            journal = RunJournal(self.metadata / "history.db")
            try:
                workflow = load_workflow(workflow_file(self.workflows, entry["name"]))
                journal.start(run_id, entry["name"], workflow.get("target", "browser"), len(workflow["steps"]))
                values = _inputs(entry.get("dataFile"), workflow)
                run_workflow(workflow, values, approve_writes=entry["approveWrites"], run_id=run_id,
                    artifacts_dir=self.workflows.parent / "runs")
                status = "completed"
            except (WorkflowError, OSError, ValueError):
                pass  # Never save or print input values, exceptions or browser contents.
            finally:
                if journal.get(run_id) is not None:
                    journal.finish(run_id, status, round((time.monotonic() - started) * 1000))
                with self._lock():
                    entries = self._load()
                    for item in entries:
                        if item.get("name") == entry["name"] and item.get("lastRunAt") == now:
                            item["lastState"] = status
                    self._save(entries)
            outcomes.append({"name": entry["name"], "state": status, "runId": run_id})
        return outcomes

    def serve(self, poll_seconds: int = 10, *, once: bool = False) -> None:
        if type(poll_seconds) is not int or not 1 <= poll_seconds <= 300:
            raise WorkflowError("poll_seconds must be between 1 and 300")
        if once:
            print(json.dumps(self.run_due(), indent=2))
            return
        print("Human2API local scheduler running (Ctrl+C to stop). No cloud account required.")
        try:
            while True:
                events = self.run_due()
                for event in events:
                    print(json.dumps(event, ensure_ascii=False), flush=True)
                time.sleep(poll_seconds)
        except KeyboardInterrupt:
            pass
