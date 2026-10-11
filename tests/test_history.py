"""Metadata-only persistent audit history; secrets must never be written."""
from __future__ import annotations
import json
import sqlite3
import time
from pathlib import Path
from urllib.request import Request, urlopen
from unittest.mock import patch

from human2api.history import RunJournal
from human2api.models import save_workflow
from human2api.http_server import make_server


def test_journal_lifecycle_and_restart(tmp_path):
    path = tmp_path / ".h2a" / "history.db"
    journal = RunJournal(path)
    journal.start("f00a", "example", "browser", 2)
    assert journal.get("f00a")["state"] == "running"
    reloaded = RunJournal(path)
    assert reloaded.get("f00a")["state"] == "interrupted"
    reloaded.finish("f00a", "completed", 55)
    record = reloaded.get("f00a")
    assert record["durationMs"] == 55 and record["state"] == "completed"
    assert reloaded.list()[0] == record


def test_journal_rejects_invalid_limits_and_states(tmp_path):
    db = RunJournal(tmp_path / "db.sqlite")
    for limit in (-1, 0, 101):
        try: db.list(limit)
        except ValueError: pass
        else: raise AssertionError("invalid limit accepted")
    try: db.finish("notfound", "exploit", 10)
    except ValueError: pass
    else: raise AssertionError("invalid state accepted")


def test_journal_prunes_old_rows(tmp_path):
    db = RunJournal(tmp_path / "log.sqlite")
    with sqlite3.connect(db.path) as conn:
        conn.execute("INSERT INTO runs VALUES ('old','stale','desktop','completed',?,?,?,?)", (int(time.time()) - 60 * 24 * 3600, int(time.time()), 1, 1))
    db.start("new", "current", "android", 1)
    assert db.get("old") is None
    assert len(db.list()) == 1


def test_journal_never_contains_secrets_or_outputs(tmp_path):
    db = RunJournal(tmp_path / "private.db")
    db.start("aabbcc", "my_flow", "browser", 1)
    db.finish("aabbcc", "failed", 42)
    fields = {row[1] for row in sqlite3.connect(db.path).execute("PRAGMA table_info(runs)")}
    assert fields == {"run_id", "workflow", "target", "state", "created_at", "completed_at", "duration_ms", "step_count"}
    text = db.path.read_bytes()
    assert b"access_token" not in text and b"inputs" not in text and b"outputs" not in text


def test_http_history_and_restart(tmp_path):
    folder = tmp_path / "workflows"
    folder.mkdir()
    workflow = {"schemaVersion": 1, "name": "snapshot", "description": "Snapshot", "target": "desktop", "permissions": "read", "steps": [{"action": "screenshot"}], "inputs": {}}
    save_workflow(folder / "snapshot.json", workflow)
    def simulate(wf, inputs, **kwargs):
        return {"ok": True, "outputs": {"secretOutput": "token-test-private"}, "target": "desktop"}
    server = make_server(folder, port=0)
    from threading import Thread
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    root = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with patch("human2api.http_server.run_workflow", simulate):
            req = Request(root + "/api/run/snapshot", data=json.dumps({"inputs": {}}).encode(), headers={"X-H2A-Token": server.token, "Content-Type": "application/json"}, method="POST")
            with urlopen(req, timeout=3) as response: run_id = json.load(response)["runId"]
            for _ in range(100):
                with urlopen(Request(root + "/api/history", headers={"X-H2A-Token": server.token}), timeout=3) as response: history = json.load(response)["history"]
                if history and history[0]["state"] == "completed": break
                time.sleep(.01)
        assert history[0]["target"] == "desktop"
        assert "token-test-private" not in json.dumps(history)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    other = RunJournal(tmp_path / ".h2a" / "history.db")
    assert other.get(run_id)["state"] == "completed"
    assert b"token-test-private" not in other.path.read_bytes()
