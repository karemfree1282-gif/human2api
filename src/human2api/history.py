"""Private SQLite run journal containing metadata ONLY, never inputs or output values.

This deliberately omits workflow parameters, screenshots, URLs, error tracebacks,
full results, authentication tokens, and secret values. Each API server owns an
on-disk journal under .h2a/, which is excluded from Git.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

MAX_HISTORY = 1000
RETENTION_SECONDS = 30 * 24 * 3600


class RunJournal:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                workflow TEXT NOT NULL,
                target TEXT NOT NULL,
                state TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                completed_at INTEGER,
                duration_ms INTEGER,
                step_count INTEGER NOT NULL
            )""")
            # A previously-running task cannot survive process shutdown.
            db.execute("UPDATE runs SET state='interrupted',completed_at=? WHERE state='running'", (int(time.time()),))
            self._prune(db)

    def _connection(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5)

    @staticmethod
    def _prune(db: sqlite3.Connection) -> None:
        db.execute("DELETE FROM runs WHERE created_at < ?", (int(time.time())-RETENTION_SECONDS,))
        db.execute("""DELETE FROM runs WHERE run_id IN (
            SELECT run_id FROM runs ORDER BY created_at DESC, rowid DESC LIMIT -1 OFFSET ?
        )""", (MAX_HISTORY,))

    def start(self, run_id: str, workflow: str, target: str, step_count: int) -> None:
        with self._connection() as db:
            db.execute("INSERT INTO runs (run_id, workflow, target, state, created_at, step_count) VALUES (?, ?, ?, 'running', ?, ?)",
                       (run_id, workflow, target, int(time.time()), step_count))
            self._prune(db)

    def finish(self, run_id: str, state: str, duration_ms: int) -> None:
        if state not in {"completed", "failed", "interrupted", "cancelled"}:
            raise ValueError("invalid final state")
        with self._connection() as db:
            db.execute("UPDATE runs SET state=?, completed_at=?, duration_ms=? WHERE run_id=?",
                       (state, int(time.time()), max(duration_ms, 0), run_id))

    @staticmethod
    def _row(row: tuple[Any, ...]) -> dict[str, Any]:
        return dict(zip(("runId", "workflow", "target", "state", "createdAt", "completedAt", "durationMs", "steps"), row))

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        if not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        with self._connection() as db:
            rows = db.execute("SELECT run_id, workflow, target, state, created_at, completed_at, duration_ms, step_count FROM runs ORDER BY created_at DESC,rowid DESC LIMIT ?", (limit,)).fetchall()
        return [self._row(row) for row in rows]

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._connection() as db:
            row = db.execute("SELECT run_id, workflow, target, state, created_at, completed_at, duration_ms, step_count FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return self._row(row) if row else None
