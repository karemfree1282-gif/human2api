"""Operator-only consistent SQLite backups. Never overwrite an existing registry."""
from __future__ import annotations
import hashlib
import os
import sqlite3
from pathlib import Path
from .models import WorkflowError


def backup(store, destination: Path) -> str:
    destination = Path(destination)
    if destination.exists() or destination.is_symlink() or not destination.parent.is_dir():
        raise WorkflowError("backup needs a new file in an existing private directory")
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    try:
        target = sqlite3.connect(destination)
        try:
            with store.connect() as source:
                source.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise WorkflowError("backup integrity check failed")
        finally:
            target.close()
        return hashlib.sha256(destination.read_bytes()).hexdigest()
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def restore(source: Path, directory: Path) -> None:
    source, directory = Path(source), Path(directory)
    if source.is_symlink() or not source.is_file() or directory.exists() or directory.is_symlink():
        raise WorkflowError("restore requires a regular operator-trusted backup and a NEW directory")
    db = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise WorkflowError("invalid backup integrity")
        tables = {x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"publishers", "packages", "ratings", "audit"}.issubset(tables):
            raise WorkflowError("not a registry backup")
        directory.mkdir(parents=True, mode=0o700)
        dest = directory / "registry.sqlite3"
        fd = os.open(dest, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600); os.close(fd)
        target = sqlite3.connect(dest)
        try:
            db.backup(target)
        finally:
            target.close()
    finally:
        db.close()
