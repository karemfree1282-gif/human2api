"""SQLite Hot Backup and Verified Restore for the Human2API Marketplace Registry."""

from __future__ import annotations

import hashlib
import json
import pathlib
import sqlite3
from typing import Any, Dict


def backup_registry_db(source_db: pathlib.Path, backup_dir: pathlib.Path) -> Dict[str, Any]:
    """Perform a consistent online SQLite backup using sqlite3.Connection.backup and write a SHA-256 manifest."""
    source_db = pathlib.Path(source_db)
    backup_dir = pathlib.Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest_db = backup_dir / "registry_backup.sqlite3"
    if dest_db.exists():
        dest_db.unlink()

    src_conn = sqlite3.connect(str(source_db))
    dst_conn = sqlite3.connect(str(dest_db))
    try:
        with dst_conn:
            src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()

    sha256_hex = hashlib.sha256(dest_db.read_bytes()).hexdigest()
    meta = {
        "backup_file": dest_db.name,
        "sha256": sha256_hex,
        "size_bytes": dest_db.stat().st_size,
    }
    (backup_dir / "backup_manifest.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def restore_registry_db(backup_dir: pathlib.Path, target_db: pathlib.Path) -> Dict[str, Any]:
    """Verify the backup SHA-256 digest before restoring the SQLite database."""
    backup_dir = pathlib.Path(backup_dir)
    target_db = pathlib.Path(target_db)
    manifest_path = backup_dir / "backup_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Backup manifest missing in {backup_dir}")
    meta = json.loads(manifest_path.read_text(encoding="utf-8"))
    backup_file = backup_dir / meta["backup_file"]
    actual_sha = hashlib.sha256(backup_file.read_bytes()).hexdigest()
    if actual_sha != meta["sha256"]:
        raise PermissionError(f"Registry backup SHA-256 mismatch: expected {meta['sha256']}, got {actual_sha}")

    target_db.parent.mkdir(parents=True, exist_ok=True)
    if target_db.exists():
        target_db.unlink()
    src_conn = sqlite3.connect(str(backup_file))
    dst_conn = sqlite3.connect(str(target_db))
    try:
        with dst_conn:
            src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()
    return {"restored": str(target_db), "sha256": actual_sha}
