"""Encrypted Secret Vault using AES-256-GCM and scrypt KDF with auto-lock timeout."""

from __future__ import annotations

import base64
import json
import os
import pathlib
import stat
import time
from typing import Dict, List, Optional, Set

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt


class VaultLockedError(PermissionError):
    """Raised when attempting to read or write secrets while the vault is locked."""


class VaultAuthenticationError(PermissionError):
    """Raised when the vault passphrase is invalid or ciphertext integrity check fails."""


class SecretVault:
    """Authenticated AES-256-GCM encrypted secret store with scrypt key derivation."""

    VERSION = 1
    SALT_BYTES = 16
    NONCE_BYTES = 12
    DEFAULT_TIMEOUT_SECONDS = 300.0

    def __init__(
        self,
        vault_path: pathlib.Path,
        unlock_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.vault_path = pathlib.Path(vault_path)
        self.unlock_timeout_seconds = float(unlock_timeout_seconds)
        self._key: Optional[bytes] = None
        self._unlocked_until: float = 0.0
        self._cache: Dict[str, str] = {}

    @staticmethod
    def _derive_key(passphrase: str, salt: bytes) -> bytes:
        if not passphrase or len(passphrase) < 4:
            raise ValueError("Vault passphrase must be at least 4 characters.")
        kdf = Scrypt(
            salt=salt,
            length=32,
            n=2**14,
            r=8,
            p=1,
        )
        return kdf.derive(passphrase.encode("utf-8"))

    def is_initialized(self) -> bool:
        return self.vault_path.exists()

    def is_unlocked(self) -> bool:
        if self._key is None:
            return False
        if time.monotonic() > self._unlocked_until:
            self.lock()
            return False
        return True

    def lock(self) -> None:
        self._key = None
        self._unlocked_until = 0.0
        self._cache.clear()

    def initialize(self, passphrase: str, initial_secrets: Optional[Dict[str, str]] = None) -> None:
        salt = os.urandom(self.SALT_BYTES)
        self._key = self._derive_key(passphrase, salt)
        self._unlocked_until = time.monotonic() + self.unlock_timeout_seconds
        self._cache = dict(initial_secrets or {})
        self._persist(salt)

    def unlock(self, passphrase: str) -> None:
        if not self.vault_path.exists():
            self.initialize(passphrase)
            return
        raw = json.loads(self.vault_path.read_text(encoding="utf-8"))
        salt = base64.b64decode(raw["salt"])
        nonce = base64.b64decode(raw["nonce"])
        ciphertext = base64.b64decode(raw["ciphertext"])
        key = self._derive_key(passphrase, salt)
        aesgcm = AESGCM(key)
        try:
            plaintext = aesgcm.decrypt(nonce, ciphertext, b"human2api-vault-v1")
        except InvalidTag as exc:
            self.lock()
            raise VaultAuthenticationError("Invalid vault passphrase or tampered vault file.") from exc
        data = json.loads(plaintext.decode("utf-8"))
        if not isinstance(data, dict):
            raise VaultAuthenticationError("Corrupted vault payload.")
        self._key = key
        self._unlocked_until = time.monotonic() + self.unlock_timeout_seconds
        self._cache = {str(k): str(v) for k, v in data.items()}

    def _require_unlocked(self) -> bytes:
        if not self.is_unlocked() or self._key is None:
            raise VaultLockedError("SecretVault is locked or session expired. Unlock required.")
        self._unlocked_until = time.monotonic() + self.unlock_timeout_seconds
        return self._key

    def _persist(self, salt: Optional[bytes] = None) -> None:
        key = self._require_unlocked()
        if salt is None:
            if self.vault_path.exists():
                existing = json.loads(self.vault_path.read_text(encoding="utf-8"))
                salt = base64.b64decode(existing["salt"])
            else:
                salt = os.urandom(self.SALT_BYTES)
        nonce = os.urandom(self.NONCE_BYTES)
        aesgcm = AESGCM(key)
        payload = json.dumps(self._cache, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ciphertext = aesgcm.encrypt(nonce, payload, b"human2api-vault-v1")
        envelope = {
            "version": self.VERSION,
            "kdf": "scrypt",
            "cipher": "AES-256-GCM",
            "salt": base64.b64encode(salt).decode("ascii"),
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        }
        self.vault_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.vault_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")
        try:
            os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        tmp_path.replace(self.vault_path)

    def set_secret(self, name: str, value: str) -> None:
        self._require_unlocked()
        if not name or not name.strip():
            raise ValueError("Secret name cannot be empty.")
        self._cache[name.strip()] = str(value)
        self._persist()

    def get_secret(self, name: str) -> str:
        self._require_unlocked()
        if name not in self._cache:
            raise KeyError(f"Secret {name!r} not found in vault.")
        return self._cache[name]

    def delete_secret(self, name: str) -> bool:
        self._require_unlocked()
        if name in self._cache:
            del self._cache[name]
            self._persist()
            return True
        return False

    def list_secret_names(self) -> List[str]:
        self._require_unlocked()
        return sorted(self._cache.keys())

    def all_secret_values(self) -> Set[str]:
        """Used exclusively by the redaction filter to strip secrets from logs/outputs."""
        if not self.is_unlocked():
            return set()
        return {v for v in self._cache.values() if v}

    def __repr__(self) -> str:
        state = "unlocked" if self.is_unlocked() else "locked"
        return f"<SecretVault path={str(self.vault_path)!r} state={state!r}>"
