"""HTTPS/loopback registry install and explicit, provenance-checked upgrades."""
from __future__ import annotations
import hashlib
import json
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, quote
from urllib.request import Request, build_opener

from .editor import revision, save_revision
from .healing import _NoRedirect
from .marketplace import MAX_PACKAGE, inspect_package
from .models import WorkflowError, workflow_file
from .registry import PUBLISHER, VERSION


def _fetch(url: str, maximum: int) -> bytes:
    parsed=urlsplit(url)
    if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise WorkflowError("invalid registry URL")
    if parsed.scheme!="https" and not (parsed.scheme=="http" and parsed.hostname in {"127.0.0.1","localhost","::1"}):
        raise WorkflowError("registry requires HTTPS, except local loopback")
    with build_opener(_NoRedirect()).open(Request(url,headers={"User-Agent":"Human2API Registry Client"}),timeout=20) as response:
        data=response.read(maximum+1)
    if len(data)>maximum:
        raise WorkflowError("registry response exceeds limit")
    return data


def install(origin: str, publisher: str, name: str, version: str, directory: Path, public_key: Path,
            *, approve: bool = False, upgrade: bool = False) -> Path:
    if not approve:
        raise WorkflowError("installation requires explicit approval after reviewing the workflow")
    if not PUBLISHER.fullmatch(publisher) or not VERSION.fullmatch(version):
        raise WorkflowError("invalid publisher/version")
    path=workflow_file(directory,name)
    origin=origin.rstrip("/")
    payload=_fetch(origin+"/v1/packages/"+"/".join(quote(x,safe="") for x in (publisher,name,version)),MAX_PACKAGE)
    with tempfile.TemporaryDirectory(prefix="h2a-install-") as temp:
        package=Path(temp)/"skill.h2a.zip";package.write_bytes(payload)
        manifest,workflow=inspect_package(package,trust_key=public_key)
    if manifest["publisher"]!=publisher or manifest["name"]!=name:
        raise WorkflowError("package identity differs from requested package")
    if manifest.get("releaseVersion") != version:
        raise WorkflowError("signed releaseVersion differs from requested version")
    metadata_dir=directory.parent/".h2a"/"installed"
    metadata_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
    metadata_path=metadata_dir/(name+".json")
    if metadata_path.is_symlink():
        raise WorkflowError("installed provenance cannot be a symlink")
    expected=revision(path)
    if expected!="new":
        if not upgrade or not metadata_path.is_file():
            raise WorkflowError("existing workflow requires --upgrade and verified installation provenance")
        old=json.loads(metadata_path.read_text(encoding="utf-8"))
        if old.get("publisher")!=publisher or old.get("publicKey")!=manifest["publicKey"] or old.get("origin")!=origin:
            raise WorkflowError("publisher key or registry changed; explicit re-enrollment is required")
        if old.get("workflowRevision")!=expected:
            raise WorkflowError("installed workflow was edited locally; merge changes manually")
        if tuple(map(int,version.split('.'))) <= tuple(map(int,old['version'].split('.'))):
            raise WorkflowError("upgrade must use a newer version; downgrades are not automatic")
    current=save_revision(directory,name,workflow,expected)
    record={"origin":origin,"publisher":publisher,"name":name,"version":version,"publicKey":manifest["publicKey"],
            "packageSha256":hashlib.sha256(payload).hexdigest(),"workflowRevision":current}
    # Provenance has no secrets. A missing record fails closed on any later upgrade.
    from .models import save_workflow
    import os
    fd,temp=tempfile.mkstemp(prefix=".installed-",dir=metadata_dir)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as stream:json.dump(record,stream)
        os.replace(temp,metadata_path)
    finally:
        Path(temp).unlink(missing_ok=True)
    return path
