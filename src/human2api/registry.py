"""SQLite-backed Marketplace & Tool Registry with Publisher Accounts, Key Pinning, Reviews, Yanking, Abuse Reports, and Audit Logs."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import pathlib
import secrets
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from human2api.models import Workflow
from human2api.trust import (
    UntrustedPackageError,
    unpack_and_verify_package_zip,
    verify_package_signature,
)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class ToolRegistry:
    """Production Marketplace Registry with serialized SQLite transactions (`BEGIN IMMEDIATE`),
    Ed25519 signature verification, version diffing, verified reviews, yanking, abuse reporting,
    and tamper-evident administrative audit logs.
    """

    def __init__(self, db_path: pathlib.Path) -> None:
        self.db_path = pathlib.Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def _init_db(self) -> None:
        with self._write_lock:
            conn = self._connect()
            try:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS publishers (
                        publisher_id TEXT PRIMARY KEY,
                        display_name TEXT NOT NULL,
                        public_key TEXT NOT NULL,
                        token_hash TEXT NOT NULL,
                        revoked INTEGER NOT NULL DEFAULT 0,
                        created_at REAL NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS packages (
                        tool_id TEXT NOT NULL,
                        version TEXT NOT NULL,
                        publisher_id TEXT NOT NULL,
                        category TEXT NOT NULL DEFAULT 'general',
                        target TEXT NOT NULL,
                        description TEXT NOT NULL DEFAULT '',
                        manifest_json TEXT NOT NULL,
                        workflow_json TEXT NOT NULL,
                        zip_blob BLOB NOT NULL,
                        sha256 TEXT NOT NULL,
                        yanked INTEGER NOT NULL DEFAULT 0,
                        yank_reason TEXT DEFAULT '',
                        published_at REAL NOT NULL,
                        PRIMARY KEY (tool_id, version),
                        FOREIGN KEY (publisher_id) REFERENCES publishers(publisher_id)
                    );

                    CREATE TABLE IF NOT EXISTS reviews (
                        review_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tool_id TEXT NOT NULL,
                        version TEXT NOT NULL,
                        reviewer_publisher_id TEXT NOT NULL,
                        rating INTEGER NOT NULL CHECK(rating >= 1 AND rating <= 5),
                        comment TEXT NOT NULL,
                        created_at REAL NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS abuse_reports (
                        report_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tool_id TEXT NOT NULL,
                        version TEXT NOT NULL,
                        reporter TEXT NOT NULL,
                        reason TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'open',
                        created_at REAL NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS audit_logs (
                        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        actor TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        target_id TEXT NOT NULL,
                        details_json TEXT NOT NULL,
                        prev_hash TEXT NOT NULL,
                        entry_hash TEXT NOT NULL,
                        created_at REAL NOT NULL
                    );
                    """
                )
            finally:
                conn.close()

    def _append_audit_in_tx(
        self,
        conn: sqlite3.Connection,
        actor: str,
        event_type: str,
        target_id: str,
        details: Dict[str, Any],
    ) -> None:
        row = conn.execute("SELECT entry_hash FROM audit_logs ORDER BY log_id DESC LIMIT 1").fetchone()
        prev_hash = str(row["entry_hash"]) if row else "0" * 64
        now = time.time()
        details_str = json.dumps(details, ensure_ascii=False, sort_keys=True)
        digest_input = f"{prev_hash}|{actor}|{event_type}|{target_id}|{details_str}|{now:.6f}".encode("utf-8")
        entry_hash = hashlib.sha256(digest_input).hexdigest()
        conn.execute(
            """
            INSERT INTO audit_logs (actor, event_type, target_id, details_json, prev_hash, entry_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (actor, event_type, target_id, details_str, prev_hash, entry_hash, now),
        )

    def _authenticate_publisher_in_tx(self, conn: sqlite3.Connection, publisher_id: str, token: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM publishers WHERE publisher_id = ?",
            (publisher_id,),
        ).fetchone()
        if row is None:
            raise PermissionError(f"Unknown publisher_id: {publisher_id!r}")
        if int(row["revoked"]) != 0:
            raise PermissionError(f"Publisher account {publisher_id!r} has been revoked.")
        expected_hash = str(row["token_hash"])
        actual_hash = _hash_token(token or "")
        if not secrets.compare_digest(expected_hash, actual_hash):
            raise PermissionError("Invalid publisher authentication token.")
        return row

    def register_publisher(self, publisher_id: str, display_name: str, public_key_b64: str) -> str:
        """Register a new publisher account and return their one-time plaintext API token."""
        if not publisher_id or not publisher_id.strip():
            raise ValueError("publisher_id cannot be empty.")
        raw_token = f"h2apub_{secrets.token_urlsafe(24)}"
        token_hash = _hash_token(raw_token)
        with self._write_lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE;")
                existing = conn.execute(
                    "SELECT publisher_id FROM publishers WHERE publisher_id = ?",
                    (publisher_id,),
                ).fetchone()
                if existing:
                    conn.execute("ROLLBACK;")
                    raise ValueError(f"Publisher {publisher_id!r} is already registered.")
                conn.execute(
                    """
                    INSERT INTO publishers (publisher_id, display_name, public_key, token_hash, revoked, created_at)
                    VALUES (?, ?, ?, ?, 0, ?)
                    """,
                    (publisher_id, display_name, public_key_b64, token_hash, time.time()),
                )
                self._append_audit_in_tx(
                    conn,
                    actor=publisher_id,
                    event_type="publisher.register",
                    target_id=publisher_id,
                    details={"display_name": display_name, "public_key": public_key_b64},
                )
                conn.execute("COMMIT;")
                return raw_token
            except Exception:
                try:
                    conn.execute("ROLLBACK;")
                except Exception:
                    pass
                raise
            finally:
                conn.close()

    def rotate_publisher_key_and_token(
        self,
        publisher_id: str,
        current_token: str,
        new_public_key_b64: Optional[str] = None,
    ) -> str:
        """Rotate publisher API token (and optionally Ed25519 public key) under an exclusive SQLite write lock."""
        new_token = f"h2apub_{secrets.token_urlsafe(24)}"
        new_hash = _hash_token(new_token)
        with self._write_lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE;")
                pub_row = self._authenticate_publisher_in_tx(conn, publisher_id, current_token)
                eff_pub_key = new_public_key_b64 or str(pub_row["public_key"])
                conn.execute(
                    "UPDATE publishers SET token_hash = ?, public_key = ? WHERE publisher_id = ?",
                    (new_hash, eff_pub_key, publisher_id),
                )
                self._append_audit_in_tx(
                    conn,
                    actor=publisher_id,
                    event_type="publisher.rotate_credentials",
                    target_id=publisher_id,
                    details={"key_rotated": bool(new_public_key_b64)},
                )
                conn.execute("COMMIT;")
                return new_token
            except Exception:
                try:
                    conn.execute("ROLLBACK;")
                except Exception:
                    pass
                raise
            finally:
                conn.close()

    def revoke_publisher(self, publisher_id: str, admin_actor: str = "admin", reason: str = "policy_violation") -> None:
        with self._write_lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE;")
                conn.execute("UPDATE publishers SET revoked = 1 WHERE publisher_id = ?", (publisher_id,))
                conn.execute(
                    "UPDATE packages SET yanked = 1, yank_reason = ? WHERE publisher_id = ?",
                    (f"Publisher revoked: {reason}", publisher_id),
                )
                self._append_audit_in_tx(
                    conn,
                    actor=admin_actor,
                    event_type="publisher.revoke",
                    target_id=publisher_id,
                    details={"reason": reason},
                )
                conn.execute("COMMIT;")
            finally:
                conn.close()

    def publish_package(
        self,
        publisher_id: str,
        token: str,
        zip_bytes: bytes,
        category: str = "automation",
    ) -> Dict[str, Any]:
        """Verify Ed25519 signature against registered publisher key and store immutable version."""
        with self._write_lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE;")
                pub_row = self._authenticate_publisher_in_tx(conn, publisher_id, token)
                trusted_key = str(pub_row["public_key"])
                manifest, wf = unpack_and_verify_package_zip(zip_bytes, trusted_public_key_b64=trusted_key)
                if manifest["publisher_id"] != publisher_id:
                    raise PermissionError("Package manifest publisher_id does not match authenticated publisher.")
                tool_id = str(manifest["tool_id"])
                version = str(manifest["version"])

                # Ensure tool_id ownership isn't hijacked by another publisher
                owner_row = conn.execute(
                    "SELECT DISTINCT publisher_id FROM packages WHERE tool_id = ?",
                    (tool_id,),
                ).fetchone()
                if owner_row and str(owner_row["publisher_id"]) != publisher_id:
                    raise PermissionError(f"Tool {tool_id!r} is owned by another publisher.")

                dup = conn.execute(
                    "SELECT 1 FROM packages WHERE tool_id = ? AND version = ?",
                    (tool_id, version),
                ).fetchone()
                if dup:
                    raise ValueError(f"Package {tool_id}@{version} already exists (versions are immutable).")

                pkg_sha256 = hashlib.sha256(zip_bytes).hexdigest()
                now = time.time()
                conn.execute(
                    """
                    INSERT INTO packages (
                        tool_id, version, publisher_id, category, target, description,
                        manifest_json, workflow_json, zip_blob, sha256, yanked, published_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                    """,
                    (
                        tool_id,
                        version,
                        publisher_id,
                        category,
                        wf.target,
                        wf.description or wf.name,
                        json.dumps(manifest, ensure_ascii=False),
                        wf.to_json(indent=2),
                        sqlite3.Binary(zip_bytes),
                        pkg_sha256,
                        now,
                    ),
                )
                self._append_audit_in_tx(
                    conn,
                    actor=publisher_id,
                    event_type="package.publish",
                    target_id=f"{tool_id}@{version}",
                    details={"sha256": pkg_sha256, "category": category, "target": wf.target},
                )
                conn.execute("COMMIT;")
                return {
                    "tool_id": tool_id,
                    "version": version,
                    "publisher_id": publisher_id,
                    "sha256": pkg_sha256,
                    "target": wf.target,
                    "category": category,
                }
            except Exception:
                try:
                    conn.execute("ROLLBACK;")
                except Exception:
                    pass
                raise
            finally:
                conn.close()

    def yank_package(self, publisher_id: str, token: str, tool_id: str, version: str, reason: str = "security") -> None:
        """Yank/withdraw a broken or malicious package version under SQLite write lock."""
        with self._write_lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE;")
                self._authenticate_publisher_in_tx(conn, publisher_id, token)
                row = conn.execute(
                    "SELECT publisher_id FROM packages WHERE tool_id = ? AND version = ?",
                    (tool_id, version),
                ).fetchone()
                if row is None:
                    raise KeyError(f"Package {tool_id}@{version} not found.")
                if str(row["publisher_id"]) != publisher_id:
                    raise PermissionError("Cannot yank a package owned by another publisher.")
                conn.execute(
                    "UPDATE packages SET yanked = 1, yank_reason = ? WHERE tool_id = ? AND version = ?",
                    (reason, tool_id, version),
                )
                self._append_audit_in_tx(
                    conn,
                    actor=publisher_id,
                    event_type="package.yank",
                    target_id=f"{tool_id}@{version}",
                    details={"reason": reason},
                )
                conn.execute("COMMIT;")
            except Exception:
                try:
                    conn.execute("ROLLBACK;")
                except Exception:
                    pass
                raise
            finally:
                conn.close()

    def add_review(
        self,
        reviewer_publisher_id: str,
        token: str,
        tool_id: str,
        version: str,
        rating: int,
        comment: str,
    ) -> Dict[str, Any]:
        """Add an authenticated review (re-verifying reviewer publisher token and revocation state inside write lock)."""
        if not (1 <= int(rating) <= 5):
            raise ValueError("Rating must be between 1 and 5.")
        with self._write_lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE;")
                self._authenticate_publisher_in_tx(conn, reviewer_publisher_id, token)
                pkg = conn.execute(
                    "SELECT yanked FROM packages WHERE tool_id = ? AND version = ?",
                    (tool_id, version),
                ).fetchone()
                if pkg is None:
                    raise KeyError(f"Package {tool_id}@{version} not found.")
                if int(pkg["yanked"]) != 0:
                    raise ValueError("Cannot review a yanked package version.")
                now = time.time()
                conn.execute(
                    """
                    INSERT INTO reviews (tool_id, version, reviewer_publisher_id, rating, comment, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (tool_id, version, reviewer_publisher_id, int(rating), comment.strip(), now),
                )
                self._append_audit_in_tx(
                    conn,
                    actor=reviewer_publisher_id,
                    event_type="package.review",
                    target_id=f"{tool_id}@{version}",
                    details={"rating": int(rating)},
                )
                conn.execute("COMMIT;")
                return {
                    "tool_id": tool_id,
                    "version": version,
                    "reviewer": reviewer_publisher_id,
                    "rating": int(rating),
                    "comment": comment.strip(),
                }
            except Exception:
                try:
                    conn.execute("ROLLBACK;")
                except Exception:
                    pass
                raise
            finally:
                conn.close()

    def report_suspicious_tool(self, tool_id: str, version: str, reporter: str, reason: str) -> Dict[str, Any]:
        if not reason or not reason.strip():
            raise ValueError("Abuse report reason cannot be empty.")
        with self._write_lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE;")
                now = time.time()
                cur = conn.execute(
                    """
                    INSERT INTO abuse_reports (tool_id, version, reporter, reason, status, created_at)
                    VALUES (?, ?, ?, ?, 'open', ?)
                    """,
                    (tool_id, version, reporter, reason.strip(), now),
                )
                report_id = cur.lastrowid
                self._append_audit_in_tx(
                    conn,
                    actor=reporter,
                    event_type="package.abuse_report",
                    target_id=f"{tool_id}@{version}",
                    details={"report_id": report_id, "reason": reason.strip()},
                )
                conn.execute("COMMIT;")
                return {"report_id": report_id, "tool_id": tool_id, "version": version, "status": "open"}
            finally:
                conn.close()

    def search_packages(
        self,
        query: str = "",
        category: Optional[str] = None,
        target: Optional[str] = None,
        include_yanked: bool = False,
    ) -> List[Dict[str, Any]]:
        conn = self._connect()
        try:
            sql = """
            SELECT p.tool_id, p.version, p.publisher_id, p.category, p.target, p.description,
                   p.sha256, p.yanked, p.yank_reason, p.published_at, p.workflow_json,
                   COALESCE(AVG(r.rating), 0.0) AS avg_rating,
                   COUNT(r.review_id) AS review_count
            FROM packages p
            LEFT JOIN reviews r ON p.tool_id = r.tool_id AND p.version = r.version
            WHERE 1=1
            """
            params: List[Any] = []
            if not include_yanked:
                sql += " AND p.yanked = 0"
            if query:
                sql += " AND (p.tool_id LIKE ? OR p.description LIKE ?)"
                q_like = f"%{query}%"
                params.extend([q_like, q_like])
            if category:
                sql += " AND p.category = ?"
                params.append(category)
            if target:
                sql += " AND p.target = ?"
                params.append(target)
            sql += " GROUP BY p.tool_id, p.version ORDER BY p.published_at DESC"
            rows = conn.execute(sql, params).fetchall()
            results: List[Dict[str, Any]] = []
            for row in rows:
                wf_data = json.loads(row["workflow_json"])
                results.append(
                    {
                        "tool_id": row["tool_id"],
                        "version": row["version"],
                        "publisher_id": row["publisher_id"],
                        "category": row["category"],
                        "target": row["target"],
                        "description": row["description"],
                        "sha256": row["sha256"],
                        "yanked": bool(row["yanked"]),
                        "yank_reason": row["yank_reason"],
                        "avg_rating": round(float(row["avg_rating"]), 2),
                        "review_count": int(row["review_count"]),
                        "permissions": {
                            "mode": wf_data.get("mode", "read"),
                            "networkPolicy": wf_data.get("networkPolicy", "strict"),
                            "allowedHosts": wf_data.get("allowedHosts", []),
                            "allowedApps": wf_data.get("allowedApps", []),
                            "allowedPackages": wf_data.get("allowedPackages", []),
                        },
                    }
                )
            return results
        finally:
            conn.close()

    def get_package_details(self, tool_id: str, version: Optional[str] = None) -> Dict[str, Any]:
        conn = self._connect()
        try:
            if version:
                row = conn.execute(
                    "SELECT * FROM packages WHERE tool_id = ? AND version = ?",
                    (tool_id, version),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM packages WHERE tool_id = ? AND yanked = 0 ORDER BY published_at DESC LIMIT 1",
                    (tool_id,),
                ).fetchone()
            if row is None:
                raise KeyError(f"Package {tool_id!r} (version={version or 'latest'}) not found.")
            wf_data = json.loads(row["workflow_json"])
            manifest_data = json.loads(row["manifest_json"])
            revs = conn.execute(
                "SELECT reviewer_publisher_id, rating, comment, created_at FROM reviews WHERE tool_id = ? AND version = ? ORDER BY created_at DESC",
                (row["tool_id"], row["version"]),
            ).fetchall()
            return {
                "tool_id": row["tool_id"],
                "version": row["version"],
                "publisher_id": row["publisher_id"],
                "category": row["category"],
                "target": row["target"],
                "description": row["description"],
                "sha256": row["sha256"],
                "yanked": bool(row["yanked"]),
                "yank_reason": row["yank_reason"],
                "manifest": manifest_data,
                "workflow": wf_data,
                "permissions": {
                    "mode": wf_data.get("mode", "read"),
                    "networkPolicy": wf_data.get("networkPolicy", "strict"),
                    "allowedHosts": wf_data.get("allowedHosts", []),
                    "allowedApps": wf_data.get("allowedApps", []),
                    "allowedPackages": wf_data.get("allowedPackages", []),
                },
                "reviews": [dict(r) for r in revs],
            }
        finally:
            conn.close()

    def download_package_bytes(self, tool_id: str, version: Optional[str] = None) -> Tuple[bytes, Dict[str, Any]]:
        conn = self._connect()
        try:
            if version:
                row = conn.execute(
                    "SELECT * FROM packages WHERE tool_id = ? AND version = ?",
                    (tool_id, version),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM packages WHERE tool_id = ? AND yanked = 0 ORDER BY published_at DESC LIMIT 1",
                    (tool_id,),
                ).fetchone()
            if row is None:
                raise KeyError(f"Package {tool_id!r} not found.")
            if int(row["yanked"]) != 0:
                raise PermissionError(f"Package {tool_id}@{row['version']} has been yanked ({row['yank_reason']}).")
            pub_row = conn.execute(
                "SELECT public_key, revoked FROM publishers WHERE publisher_id = ?",
                (row["publisher_id"],),
            ).fetchone()
            if pub_row is None or int(pub_row["revoked"]) != 0:
                raise PermissionError(f"Publisher {row['publisher_id']!r} is revoked or invalid.")
            return bytes(row["zip_blob"]), {
                "tool_id": row["tool_id"],
                "version": row["version"],
                "publisher_id": row["publisher_id"],
                "public_key": pub_row["public_key"],
                "sha256": row["sha256"],
            }
        finally:
            conn.close()

    def diff_versions(self, tool_id: str, version_a: str, version_b: str) -> Dict[str, Any]:
        """Compare permissions, inputs, and steps between two versions of a tool before upgrading."""
        det_a = self.get_package_details(tool_id, version_a)
        det_b = self.get_package_details(tool_id, version_b)
        wf_a = det_a["workflow"]
        wf_b = det_b["workflow"]

        hosts_added = sorted(set(wf_b.get("allowedHosts", [])) - set(wf_a.get("allowedHosts", [])))
        apps_added = sorted(set(wf_b.get("allowedApps", [])) - set(wf_a.get("allowedApps", [])))
        pkgs_added = sorted(set(wf_b.get("allowedPackages", [])) - set(wf_a.get("allowedPackages", [])))
        inputs_added = sorted(set((wf_b.get("inputs") or {}).keys()) - set((wf_a.get("inputs") or {}).keys()))
        mode_changed = wf_a.get("mode") != wf_b.get("mode")

        return {
            "tool_id": tool_id,
            "from_version": version_a,
            "to_version": version_b,
            "mode_changed": mode_changed,
            "old_mode": wf_a.get("mode"),
            "new_mode": wf_b.get("mode"),
            "hosts_added": hosts_added,
            "apps_added": apps_added,
            "packages_added": pkgs_added,
            "inputs_added": inputs_added,
            "step_count_delta": len(wf_b.get("steps", [])) - len(wf_a.get("steps", [])),
            "privilege_expanded": bool(hosts_added or apps_added or pkgs_added or (mode_changed and wf_b.get("mode") == "write")),
        }

    def list_audit_logs(self) -> List[Dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM audit_logs ORDER BY log_id ASC").fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def verify_audit_chain(self) -> bool:
        logs = self.list_audit_logs()
        prev = "0" * 64
        for entry in logs:
            if entry["prev_hash"] != prev:
                return False
            prev = entry["entry_hash"]
        return True
