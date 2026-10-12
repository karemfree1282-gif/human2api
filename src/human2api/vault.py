"""Password-encrypted local secret vault; explicit CLI unlock, no master-key file.

AES-256-GCM with scrypt key derivation, a random salt and fresh nonce per write.
The on-disk vault stores only KDF metadata and authenticated ciphertext. Updates
use an exclusive lock and compare-and-swap to reject stale or concurrent writes.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import tempfile
from pathlib import Path
from typing import Any

from .models import WorkflowError

MAX_SIZE = 1024 * 1024
NAME = re.compile(r"[a-zA-Z][a-zA-Z0-9_.-]{0,99}\Z")
AAD = b"human2api.vault.v1"


def _decode(value: str, size: int | None = None) -> bytes:
    raw = base64.b64decode(value, validate=True)
    if size is not None and len(raw) != size:
        raise ValueError("invalid size")
    return raw


class Vault:
    def __init__(self, path: Path, password: str, *, create: bool = False) -> None:
        try:
            from cryptography.exceptions import InvalidTag
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
        except ImportError as exc:
            raise WorkflowError("install the optional vault dependency: pip install 'human2api[vault]'") from exc
        self.path = Path(path)
        self._key: bytearray | None = None
        self._data: dict[str, str] = {}
        self._revision: str | None = None
        if not isinstance(password, str) or len(password) < 12:
            raise WorkflowError("vault passphrase must contain at least 12 characters")
        if self.path.is_symlink():
            raise WorkflowError("vault cannot be a symlink")
        if create:
            if self.path.exists():
                raise WorkflowError("vault already exists")
            self._salt = secrets.token_bytes(16)
        else:
            if not self.path.is_file() or self.path.stat().st_size > MAX_SIZE:
                raise WorkflowError("vault is missing or too large")
            if os.name != "nt" and self.path.stat().st_mode & 0o077:
                raise WorkflowError("vault must have owner-only permissions")
            raw = self.path.read_bytes()
            try:
                doc = json.loads(raw)
                if set(doc) != {"version", "salt", "nonce", "ciphertext"} or doc["version"] != 1:
                    raise ValueError("unsupported vault")
                self._salt = _decode(doc["salt"], 16)
                nonce, ciphertext = _decode(doc["nonce"], 12), _decode(doc["ciphertext"])
            except (ValueError, TypeError, KeyError) as exc:
                raise WorkflowError("invalid vault document") from exc
            self._revision = hashlib.sha256(raw).hexdigest()
        key = Scrypt(salt=self._salt, length=32, n=2**15, r=8, p=1).derive(password.encode("utf-8"))
        self._key = bytearray(key)
        if not create:
            try:
                self._data = json.loads(AESGCM(key).decrypt(nonce, ciphertext, AAD))
                if not isinstance(self._data, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in self._data.items()):
                    raise ValueError("invalid vault payload")
            except (InvalidTag, ValueError, TypeError) as exc:
                self.close()
                raise WorkflowError("wrong passphrase or modified vault") from exc
        else:
            self._save()

    def _save(self) -> None:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        if self._key is None:
            raise WorkflowError("vault is locked")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock = self.path.with_name(self.path.name + ".lock")
        try:
            lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise WorkflowError("vault is busy; no update performed") from exc
        temp = None
        try:
            os.close(lock_fd)
            if self.path.is_symlink():
                raise WorkflowError("vault cannot be a symlink")
            current = hashlib.sha256(self.path.read_bytes()).hexdigest() if self.path.exists() else None
            if current != self._revision:
                raise WorkflowError("vault changed; unlock it again before writing")
            nonce = secrets.token_bytes(12)
            plaintext = json.dumps(self._data, ensure_ascii=False).encode("utf-8")
            ciphertext = AESGCM(bytes(self._key)).encrypt(nonce, plaintext, AAD)
            encoded = lambda x: base64.b64encode(x).decode("ascii")
            data = json.dumps({"version": 1, "salt": encoded(self._salt), "nonce": encoded(nonce), "ciphertext": encoded(ciphertext)}).encode("ascii")
            if len(data) > MAX_SIZE:
                raise WorkflowError("vault exceeds size limit")
            fd, name = tempfile.mkstemp(prefix=".vault-", dir=self.path.parent)
            temp = Path(name)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, self.path)
            self._revision = hashlib.sha256(data).hexdigest()
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)
            lock.unlink(missing_ok=True)

    def names(self) -> list[str]:
        if self._key is None:
            raise WorkflowError("vault is locked")
        return sorted(self._data)

    def get(self, name: str) -> str:
        if self._key is None:
            raise WorkflowError("vault is locked")
        if name not in self._data:
            raise WorkflowError("vault entry does not exist")
        return self._data[name]

    def set(self, name: str, value: str) -> None:
        if not NAME.fullmatch(name) or not isinstance(value, str) or len(value) > 10000:
            raise WorkflowError("invalid vault entry")
        previous = dict(self._data)
        self._data[name] = value
        try:
            self._save()
        except Exception:
            self._data = previous
            raise

    def delete(self, name: str) -> None:
        if name not in self._data:
            raise WorkflowError("vault entry does not exist")
        previous = dict(self._data)
        del self._data[name]
        try:
            self._save()
        except Exception:
            self._data = previous
            raise

    def close(self) -> None:
        self._data.clear()
        if self._key is not None:
            self._key[:] = b"\x00" * len(self._key)
        self._key = None

    def __enter__(self) -> Any:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
