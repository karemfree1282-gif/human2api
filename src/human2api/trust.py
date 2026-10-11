"""Optional Ed25519 signing of inspectable Human2API workflow packages.

Keys are publisher-managed. A valid signature establishes that the signed
manifest and workflow have not changed; trust requires out-of-band key pinning.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

from .models import WorkflowError


def _crypto():
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
    except ImportError as exc:
        raise WorkflowError("signing requires: pip install 'human2api[signing]'") from exc
    return InvalidSignature, serialization, Ed25519PrivateKey, Ed25519PublicKey


def generate_keypair(private_path: Path, public_path: Path) -> None:
    """Create non-overwriting keys. The secret key is owner-only on POSIX."""
    _, serial, PrivateKey, _ = _crypto()
    private_path = Path(private_path)
    public_path = Path(public_path)
    if private_path.resolve() == public_path.resolve() or any(x.exists() or x.is_symlink() for x in (private_path, public_path)):
        raise WorkflowError("key paths must be distinct and not already exist")
    if not private_path.parent.is_dir() or not public_path.parent.is_dir():
        raise WorkflowError("create the output directories before generating keys")
    private = PrivateKey.generate()
    secret = private.private_bytes(serial.Encoding.PEM, serial.PrivateFormat.PKCS8, serial.NoEncryption())
    public = private.public_key().public_bytes(serial.Encoding.PEM, serial.PublicFormat.SubjectPublicKeyInfo)
    # O_EXCL stops accidental replacement and symlink races. Do not write keys to stdout.
    fd = os.open(private_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(secret)
        pub_fd = os.open(public_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        with os.fdopen(pub_fd, "wb") as handle:
            handle.write(public)
    except Exception:
        private_path.unlink(missing_ok=True)
        raise


def sign_bytes(payload: bytes, private_path: Path) -> tuple[str, str]:
    _, serial, PrivateKey, _ = _crypto()
    path = Path(private_path)
    if path.is_symlink() or not path.is_file():
        raise WorkflowError("private signing key must be a regular, non-symlink file")
    if os.name != "nt" and path.stat().st_mode & 0o077:
        raise WorkflowError("private key permissions are too broad; chmod 600 your key")
    try:
        private = serial.load_pem_private_key(path.read_bytes(), password=None)
    except (ValueError, TypeError) as exc:
        raise WorkflowError("invalid Ed25519 private key") from exc
    if not isinstance(private, PrivateKey):
        raise WorkflowError("private key must use Ed25519")
    public = private.public_key().public_bytes(serial.Encoding.Raw, serial.PublicFormat.Raw)
    signature = private.sign(payload)
    return base64.b64encode(public).decode("ascii"), base64.b64encode(signature).decode("ascii")


def verify_bytes(payload: bytes, public_b64: str, signature_b64: str, *, trust_key: Path | None = None) -> bool:
    InvalidSignature, serial, _, PublicKey = _crypto()
    try:
        public_raw = base64.b64decode(public_b64, validate=True)
        signed = base64.b64decode(signature_b64, validate=True)
        if len(public_raw) != 32 or len(signed) != 64:
            raise ValueError("invalid signature size")
        public = PublicKey.from_public_bytes(public_raw)
        public.verify(signed, payload)
        if trust_key is not None:
            path = Path(trust_key)
            if not path.is_file() or path.is_symlink():
                raise WorkflowError("trusted public key must be a regular, non-symlink file")
            pinned = serial.load_pem_public_key(path.read_bytes())
            if not isinstance(pinned, PublicKey):
                raise WorkflowError("trusted public key must use Ed25519")
            expected = pinned.public_bytes(serial.Encoding.Raw, serial.PublicFormat.Raw)
            if expected != public_raw:
                raise WorkflowError("package signed by a different publisher key")
        return trust_key is not None
    except WorkflowError:
        raise
    except (InvalidSignature, ValueError, TypeError, UnicodeError) as exc:
        raise WorkflowError("package publisher signature is invalid") from exc
