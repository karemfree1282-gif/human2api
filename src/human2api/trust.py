"""Cryptographic Package Signing (Ed25519), Key Pinning, and Safe Package Archive Handling (Anti-ZIP-Slip)."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import pathlib
import stat
import zipfile
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from human2api.models import Workflow

MAX_PACKAGE_BYTES = 2 * 1024 * 1024  # 2 MiB max package archive
MAX_ENTRY_BYTES = 1 * 1024 * 1024  # 1 MiB max per JSON entry
ALLOWED_PACKAGE_FILES = {"manifest.json", "workflow.json"}


class UntrustedPackageError(PermissionError):
    """Raised when a package signature, digest, or publisher key fails verification."""


class UnsafePackageArchiveError(PermissionError):
    """Raised when a package archive violates ZIP Slip, symlink, file-set, or size constraints."""


def generate_ed25519_keypair() -> Tuple[str, str]:
    """Return (private_key_b64, public_key_b64) raw 32-byte Ed25519 keys encoded in Base64."""
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    priv_raw = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_raw = pub.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(priv_raw).decode("ascii"), base64.b64encode(pub_raw).decode("ascii")


def canonical_workflow_bytes(workflow_dict: Dict[str, Any]) -> bytes:
    return json.dumps(workflow_dict, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sign_package_payload(
    private_key_b64: str,
    tool_id: str,
    version: str,
    publisher_id: str,
    workflow_dict: Dict[str, Any],
) -> Dict[str, Any]:
    """Create a version-bound Ed25519 signature over (tool_id, version, publisher_id, workflow_sha256)."""
    priv_raw = base64.b64decode(private_key_b64)
    priv = Ed25519PrivateKey.from_private_bytes(priv_raw)
    pub_raw = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    wf_bytes = canonical_workflow_bytes(workflow_dict)
    wf_sha256 = compute_sha256_hex(wf_bytes)
    signing_statement = f"h2a-pkg-v1|{tool_id}|{version}|{publisher_id}|{wf_sha256}".encode("utf-8")
    sig = priv.sign(signing_statement)
    return {
        "schema": "h2a-package-manifest-v1",
        "tool_id": tool_id,
        "version": version,
        "publisher_id": publisher_id,
        "workflow_sha256": wf_sha256,
        "public_key": base64.b64encode(pub_raw).decode("ascii"),
        "signature": base64.b64encode(sig).decode("ascii"),
    }


def verify_package_signature(
    manifest: Dict[str, Any],
    workflow_dict: Dict[str, Any],
    trusted_public_key_b64: Optional[str] = None,
) -> bool:
    """Verify package digest and version-bound Ed25519 signature against pinned/trusted public key."""
    try:
        tool_id = str(manifest["tool_id"])
        version = str(manifest["version"])
        publisher_id = str(manifest["publisher_id"])
        expected_sha = str(manifest["workflow_sha256"])
        manifest_pub_b64 = str(manifest["public_key"])
        sig_b64 = str(manifest["signature"])
    except KeyError as exc:
        raise UntrustedPackageError(f"Package manifest missing required field: {exc}") from exc

    if trusted_public_key_b64 is not None and manifest_pub_b64 != trusted_public_key_b64:
        raise UntrustedPackageError(
            "Package public key does not match the pinned/registered publisher public key."
        )

    wf_bytes = canonical_workflow_bytes(workflow_dict)
    actual_sha = compute_sha256_hex(wf_bytes)
    if actual_sha != expected_sha:
        raise UntrustedPackageError(
            f"Workflow SHA-256 mismatch: manifest expected {expected_sha}, got {actual_sha}."
        )

    pub_raw = base64.b64decode(manifest_pub_b64)
    sig_raw = base64.b64decode(sig_b64)
    pub = Ed25519PublicKey.from_public_bytes(pub_raw)
    signing_statement = f"h2a-pkg-v1|{tool_id}|{version}|{publisher_id}|{actual_sha}".encode("utf-8")
    try:
        pub.verify(sig_raw, signing_statement)
    except InvalidSignature as exc:
        raise UntrustedPackageError("Invalid Ed25519 digital signature on package.") from exc
    return True


def build_package_zip_bytes(
    workflow: Workflow,
    private_key_b64: str,
    tool_id: str,
    version: str,
    publisher_id: str,
) -> bytes:
    """Build a deterministic 2-file `.h2apkg` ZIP archive containing `manifest.json` and `workflow.json`."""
    wf_dict = workflow.to_dict()
    wf_dict["version"] = version
    manifest = sign_package_payload(
        private_key_b64=private_key_b64,
        tool_id=tool_id,
        version=version,
        publisher_id=publisher_id,
        workflow_dict=wf_dict,
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        zf.writestr("workflow.json", json.dumps(wf_dict, ensure_ascii=False, indent=2))
    return buf.getvalue()


def unpack_and_verify_package_zip(
    zip_bytes: bytes,
    trusted_public_key_b64: Optional[str] = None,
) -> Tuple[Dict[str, Any], Workflow]:
    """Safely inspect and unpack a `.h2apkg` archive in memory, blocking ZIP Slip, symlinks, executables, and zip bombs."""
    if len(zip_bytes) > MAX_PACKAGE_BYTES:
        raise UnsafePackageArchiveError(f"Package archive exceeds maximum size ({MAX_PACKAGE_BYTES} bytes).")
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes), "r")
    except Exception as exc:
        raise UnsafePackageArchiveError(f"Invalid ZIP archive: {exc}") from exc

    with zf:
        infos = zf.infolist()
        names = set()
        for info in infos:
            fname = info.filename
            # Block path traversal / ZIP Slip / absolute paths / subdirectories
            if (
                ".." in fname
                or fname.startswith("/")
                or fname.startswith("\\")
                or "/" in fname
                or "\\" in fname
            ):
                raise UnsafePackageArchiveError(f"ZIP Slip / path traversal detected in archive entry: {fname!r}")
            # Block symlinks
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise UnsafePackageArchiveError(f"Symlink entry prohibited in package archive: {fname!r}")
            if fname not in ALLOWED_PACKAGE_FILES:
                raise UnsafePackageArchiveError(
                    f"Unexpected file in package archive: {fname!r}. Only {sorted(ALLOWED_PACKAGE_FILES)} are allowed."
                )
            if info.file_size > MAX_ENTRY_BYTES:
                raise UnsafePackageArchiveError(f"Archive entry {fname!r} exceeds maximum uncompressed size.")
            names.add(fname)

        if names != ALLOWED_PACKAGE_FILES:
            raise UnsafePackageArchiveError(
                f"Package archive must contain exactly {sorted(ALLOWED_PACKAGE_FILES)}, got {sorted(names)}."
            )

        manifest_raw = json.loads(zf.read("manifest.json").decode("utf-8"))
        workflow_raw = json.loads(zf.read("workflow.json").decode("utf-8"))

    verify_package_signature(manifest_raw, workflow_raw, trusted_public_key_b64=trusted_public_key_b64)
    wf = Workflow.from_dict(workflow_raw)
    return manifest_raw, wf
