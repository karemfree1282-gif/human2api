"""Trust-minimized portable workflow packages (.h2a.zip).

Packages can contain ONLY a validated workflow JSON and a strict manifest.
No programs, plugins, scripts, binary attachments or arbitrary remote execution.
Unsigned v1 uses checksums; signed v2 adds Ed25519 publisher authenticity with pinned public keys.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .models import WorkflowError, load_workflow, save_workflow, validate_workflow, workflow_file

PKG_VERSION = 1
MAX_PACKAGE = 512 * 1024
MAX_REGISTRY = 128 * 1024
DEFAULT_CATALOG_URL = "https://raw.githubusercontent.com/karemfree1282-gif/human2api/main/marketplace/index.json"


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def pack_workflow(workflow_path: Path, destination: Path, *, publisher: str = "community", sign_key: Path | None = None, release_version: str | None = None) -> Path:
    workflow = load_workflow(workflow_path)
    if not publisher or len(publisher) > 80 or any(c in publisher for c in "\r\n\\"):
        raise WorkflowError("publisher must be a short printable name")
    payload = _canonical(workflow)
    manifest = {
        "packageVersion": PKG_VERSION,
        "name": workflow["name"], "description": workflow["description"],
        "target": workflow.get("target", "browser"), "publisher": publisher,
        "workflowSha256": hashlib.sha256(payload).hexdigest(),
        "license": "review-original-workflow-license",
    }
    if release_version is not None:
        if sign_key is None or not isinstance(release_version, str) or not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", release_version):
            raise WorkflowError("release_version requires signing and a major.minor.patch version")
        manifest["releaseVersion"] = release_version
    if sign_key is not None:
        from .trust import sign_bytes
        manifest["packageVersion"] = 2
        # Include the public key in the signed body to prevent key substitution.
        pub, _ = sign_bytes(b"", sign_key)
        manifest["signatureAlgorithm"] = "Ed25519"
        manifest["publicKey"] = pub
        _, signature = sign_bytes(_canonical(manifest), sign_key)
        manifest["signature"] = signature
    destination = Path(destination)
    if destination.suffix.lower() != ".zip" or not destination.name.endswith(".h2a.zip"):
        raise WorkflowError("package filename must end with .h2a.zip")
    if destination.exists() or destination.is_symlink():
        raise WorkflowError("package already exists; refusing to overwrite")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as out:
        out.writestr("manifest.json", _canonical(manifest))
        out.writestr("workflow.json", payload)
    return destination


def inspect_package(path: Path, *, trust_key: Path | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    path = Path(path)
    if not path.is_file() or path.stat().st_size > MAX_PACKAGE:
        raise WorkflowError("package is missing or exceeds size limit")
    try:
        with zipfile.ZipFile(path) as bundle:
            files = bundle.infolist()
            if len(files) != 2 or set(i.filename for i in files) != {"manifest.json", "workflow.json"}:
                raise WorkflowError("packages may contain only manifest.json and workflow.json")
            if any(i.file_size > MAX_PACKAGE or i.is_dir() or ((i.external_attr >> 16) & 0o170000) == 0o120000 for i in files):
                raise WorkflowError("package contains invalid files or symlinks")
            mf = json.loads(bundle.read("manifest.json"))
            wf_bytes = bundle.read("workflow.json")
            wf = json.loads(wf_bytes)
        if not isinstance(mf, dict) or mf.get("packageVersion") not in {1, 2}:
            raise WorkflowError("unsupported package manifest")
        fields = {"packageVersion", "name", "description", "target", "publisher", "workflowSha256", "license"}
        if mf["packageVersion"] == 2:
            fields.update({"signatureAlgorithm", "publicKey", "signature"})
            if "releaseVersion" in mf:
                fields.add("releaseVersion")
                if not isinstance(mf["releaseVersion"], str) or not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", mf["releaseVersion"]):
                    raise WorkflowError("invalid signed release version")
        if set(mf) != fields:
            raise WorkflowError("invalid package manifest fields")
        if mf["packageVersion"] == 2:
            if mf["signatureAlgorithm"] != "Ed25519":
                raise WorkflowError("unsupported package signature scheme")
            from .trust import verify_bytes
            pub = mf["publicKey"]
            signature = mf["signature"]
            if not isinstance(pub, str) or not isinstance(signature, str):
                raise WorkflowError("package signature fields must be strings")
            # The canonical form signs every manifest property except the signature.
            verify_bytes(_canonical({k: v for k, v in mf.items() if k != "signature"}), pub, signature, trust_key=trust_key)
        elif trust_key is not None:
            raise WorkflowError("unsigned package cannot satisfy trusted publisher verification")
        if hashlib.sha256(wf_bytes).hexdigest() != mf["workflowSha256"]:
            raise WorkflowError("package checksum mismatch")
        validate_workflow(wf)
        if wf["name"] != mf["name"] or wf["description"] != mf["description"] or wf.get("target", "browser") != mf["target"]:
            raise WorkflowError("manifest disagrees with workflow")
        return mf, wf
    except (zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, OSError) as exc:
        raise WorkflowError("invalid workflow package") from exc


def install_package(path: Path, directory: Path, *, approve: bool = False, trust_key: Path | None = None) -> Path:
    if not approve:
        raise WorkflowError("installing a third-party workflow requires --approve after inspecting its actions")
    manifest, workflow = inspect_package(path, trust_key=trust_key)
    target = workflow_file(directory, workflow["name"])
    if target.exists() or target.is_symlink():
        raise WorkflowError("installed workflow already exists; refusing to overwrite")
    return save_workflow(target, workflow)


def download_package(url: str, expected_sha256: str, *, directory: Path) -> Path:
    """Explicit, checksum-pinned HTTPS download. Does not install the package."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or not parsed.hostname or parsed.fragment:
        raise WorkflowError("package downloads require a direct HTTPS URL")
    if len(expected_sha256) != 64 or any(c not in "0123456789abcdef" for c in expected_sha256):
        raise WorkflowError("expected_sha256 must be a lowercase SHA-256 hex digest")
    req = Request(url, headers={"User-Agent": "Human2API/0.4.0"})
    from .healing import _NoRedirect
    from urllib.request import build_opener
    with build_opener(_NoRedirect()).open(req, timeout=15) as res:
        if int(res.headers.get("Content-Length", "0")) > MAX_PACKAGE:
            raise WorkflowError("package exceeds size limit")
        content = res.read(MAX_PACKAGE + 1)
    if len(content) > MAX_PACKAGE or hashlib.sha256(content).hexdigest() != expected_sha256:
        raise WorkflowError("download size/checksum mismatch")
    directory.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="h2a-download-", suffix=".h2a.zip", dir=directory)
    try:
        with os.fdopen(fd, "wb") as target:
            target.write(content)
        inspect_package(Path(name))
        return Path(name)
    except Exception:
        Path(name).unlink(missing_ok=True)
        raise


def local_catalog(directory: Path) -> list[dict[str, Any]]:
    """Enumerate audited workflow packages from a user-managed local directory."""
    results = []
    if not directory.exists():
        return results
    for path in sorted(directory.glob("*.h2a.zip")):
        if path.is_symlink():
            continue
        try:
            manifest, _ = inspect_package(path)
            results.append({**manifest, "file": str(path), "verified": True, "signatureValid": manifest["packageVersion"] == 2, "publisherTrusted": False})
        except (WorkflowError, OSError):
            continue
    return results


def remote_catalog(url: str = DEFAULT_CATALOG_URL) -> list[dict[str, Any]]:
    """Read a public HTTPS JSON index; never executes any downloaded content.

    The server's `sha256` field protects package *integrity only*. Index/host
    control determines which SHA is trusted. Use pinned-key registry installation
    for authenticated publisher packages.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise WorkflowError("remote catalog URL must be HTTPS without credentials")
    from urllib.request import build_opener
    from .healing import _NoRedirect
    try:
        with build_opener(_NoRedirect()).open(Request(url, headers={"User-Agent": "Human2API/0.4.0"}), timeout=12) as response:
            if int(response.headers.get("Content-Length", "0")) > MAX_REGISTRY:
                raise WorkflowError("remote catalog is too large")
            payload = response.read(MAX_REGISTRY + 1)
        if len(payload) > MAX_REGISTRY:
            raise WorkflowError("remote catalog is too large")
        registry = json.loads(payload)
    except WorkflowError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise WorkflowError("remote catalog could not be downloaded or parsed") from exc
    if not isinstance(registry, dict) or registry.get("formatVersion") != 1:
        raise WorkflowError("unsupported remote catalog format")
    packages = registry.get("packages")
    if not isinstance(packages, list) or len(packages) > 100:
        raise WorkflowError("remote catalog has an invalid package list")
    items = []
    from .models import NAME_RE
    for entry in packages:
        if not isinstance(entry, dict) or set(entry) != {"name", "version", "publisher", "target", "description", "url", "sha256"}:
            raise WorkflowError("invalid remote catalog entry")
        name, checksum = entry["name"], entry["sha256"]
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            raise WorkflowError("invalid remote package name")
        if not isinstance(checksum, str) or len(checksum) != 64 or any(c not in "0123456789abcdef" for c in checksum):
            raise WorkflowError("invalid remote package checksum")
        if entry["target"] not in {"browser", "android", "desktop"}:
            raise WorkflowError("invalid remote package target")
        if not all(isinstance(entry[k], str) and 0 < len(entry[k]) <= 300 for k in ("version", "publisher", "description")):
            raise WorkflowError("invalid remote package metadata")
        if not isinstance(entry["url"], str):
            raise WorkflowError("remote package URL must use HTTPS")
        target_url = urlparse(entry["url"])
        if target_url.scheme != "https" or not target_url.hostname or target_url.username or target_url.password or target_url.fragment:
            raise WorkflowError("remote package URL must use HTTPS without fragments or credentials")
        items.append(entry)
    if len({entry["name"] for entry in items}) != len(items):
        raise WorkflowError("remote catalog contains duplicate package names")
    return items


def install_remote(name: str, directory: Path, *, approve: bool, catalog_url: str = DEFAULT_CATALOG_URL, trust_key: Path | None = None) -> Path:
    """Explicit catalog fetch + checksum-verified package installation."""
    if not approve:
        raise WorkflowError("remote installation requires --approve after inspecting workflow permissions")
    catalog = remote_catalog(catalog_url)
    match = next((entry for entry in catalog if entry["name"] == name), None)
    if match is None:
        raise WorkflowError("workflow not found in remote catalog")
    with tempfile.TemporaryDirectory(prefix="h2a-verify-") as tmp:
        package = download_package(match["url"], match["sha256"], directory=Path(tmp))
        manifest, workflow = inspect_package(package, trust_key=trust_key)
        if manifest["name"] != name or workflow.get("target", "browser") != match["target"]:
            raise WorkflowError("package does not match remote index metadata")
        return install_package(package, directory, approve=True, trust_key=trust_key)
