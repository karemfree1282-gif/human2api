"""HTTPS/HTTP Client for Remote Human2API Tool Registries with checksum & signature verification."""

from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from human2api.models import Workflow
from human2api.trust import compute_sha256_hex, unpack_and_verify_package_zip


class RemoteRegistryClient:
    """Fetches catalog metadata and signed packages over HTTPS (or local TLS test servers) and verifies SHA-256 + Ed25519 signatures."""

    def __init__(self, base_url: str, ssl_context: Optional[ssl.SSLContext] = None) -> None:
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme not in ("https", "http"):
            raise ValueError(f"Unsupported registry URL scheme: {parsed.scheme!r}")
        if parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "127.0.0.2", "localhost", "::1"):
            raise PermissionError("Remote registry connections require HTTPS for non-loopback hosts.")
        self.base_url = base_url.rstrip("/")
        self.ssl_context = ssl_context

    def fetch_catalog(self) -> List[Dict[str, Any]]:
        req = urllib.request.Request(f"{self.base_url}/api/v1/marketplace/packages", method="GET")
        with urllib.request.urlopen(req, context=self.ssl_context, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("packages", [])

    def download_and_verify(
        self,
        tool_id: str,
        version: str,
        expected_sha256: Optional[str] = None,
        trusted_public_key_b64: Optional[str] = None,
    ) -> Tuple[bytes, Dict[str, Any], Workflow]:
        url = f"{self.base_url}/api/v1/marketplace/download?tool_id={urllib.parse.quote(tool_id)}&version={urllib.parse.quote(version)}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, context=self.ssl_context, timeout=10) as resp:
            zip_bytes = resp.read()
        if expected_sha256:
            actual_sha = compute_sha256_hex(zip_bytes)
            if actual_sha != expected_sha256:
                raise PermissionError(f"Downloaded package SHA-256 mismatch: expected {expected_sha256}, got {actual_sha}")
        manifest, wf = unpack_and_verify_package_zip(zip_bytes, trusted_public_key_b64=trusted_public_key_b64)
        return zip_bytes, manifest, wf
