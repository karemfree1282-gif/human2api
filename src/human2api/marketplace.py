"""Trust-minimized portable workflow packages (.h2a.zip).

Packages can contain ONLY a validated workflow JSON and a strict manifest.
No programs, plugins, scripts, binary attachments or arbitrary remote execution.
Hashes protect transfers; they are NOT a publisher identity/signature.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .models import WorkflowError, load_workflow, save_workflow, validate_workflow, workflow_file

PKG_VERSION = 1
MAX_PACKAGE = 512 * 1024


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def pack_workflow(workflow_path: Path, destination: Path, *, publisher: str = "community") -> Path:
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


def inspect_package(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
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
        if not isinstance(mf, dict) or mf.get("packageVersion") != PKG_VERSION:
            raise WorkflowError("unsupported package manifest")
        if set(mf) != {"packageVersion", "name", "description", "target", "publisher", "workflowSha256", "license"}:
            raise WorkflowError("invalid package manifest fields")
        if hashlib.sha256(wf_bytes).hexdigest() != mf["workflowSha256"]:
            raise WorkflowError("package checksum mismatch")
        validate_workflow(wf)
        if wf["name"] != mf["name"] or wf["description"] != mf["description"] or wf.get("target", "browser") != mf["target"]:
            raise WorkflowError("manifest disagrees with workflow")
        return mf, wf
    except (zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, OSError) as exc:
        raise WorkflowError("invalid workflow package") from exc


def install_package(path: Path, directory: Path, *, approve: bool = False) -> Path:
    if not approve:
        raise WorkflowError("installing a third-party workflow requires --approve after inspecting its actions")
    manifest, workflow = inspect_package(path)
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
    req = Request(url, headers={"User-Agent": "Human2API/0.2"})
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
            results.append({**manifest, "file": str(path), "verified": True})
        except (WorkflowError, OSError):
            continue
    return results
