"""One-command, evidence-based release assembly. Never converts a blocked gate to pass.

Only repairs deterministic generated files. It is not an unconstrained coding
agent, does not weaken tests, grant accessibility access, alter billing, or
install dependencies unless --bootstrap was explicitly requested.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.request import Request, build_opener, HTTPRedirectHandler

from . import __version__
from .contracts import workflow_schema
from .models import WorkflowError, load_workflow

PLATFORMS = ("windows-uia", "macos-ax", "linux-atspi", "android-companion")


def junit_summary(path: Path) -> dict[str, int]:
    """Count testcases rather than both a suite and its aggregate parent."""
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    errors = sum(1 for c in cases if c.find("error") is not None)
    failures = sum(1 for c in cases if c.find("failure") is not None)
    skipped = sum(1 for c in cases if c.find("skipped") is not None)
    # Collection/setup errors can also live directly below testsuite.
    errors += sum(len(s.findall("error")) for s in root.iter("testsuite"))
    return {"tests": len(cases), "passed": max(0, len(cases)-errors-failures-skipped),
            "failures": failures, "errors": errors, "skipped": skipped}


def source_digest(root: Path) -> str:
    h = hashlib.sha256()
    for folder in ("src", "android-companion"):
        for p in sorted((root / folder).rglob("*")):
            if p.is_file() and not p.is_symlink() and not any(x in {"__pycache__", "build", ".gradle"} or x.endswith(".egg-info") for x in p.parts):
                h.update(str(p.relative_to(root)).replace("\\", "/").encode())
                h.update(b"\0" + p.read_bytes() + b"\0")
    h.update((root / "pyproject.toml").read_bytes())
    return h.hexdigest()


def repair_generated(root: Path) -> list[str]:
    """Idempotent repair of schemas only; never edits implementation or tests."""
    from .http_server import openapi_schema
    definitions = {
        "schemas/workflow.schema.json": workflow_schema(),
        "docs/openapi.example.json": openapi_schema(root / "workflows"),
    }
    changed = []
    for name, data in definitions.items():
        p = root / name
        text = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        if p.is_symlink():
            raise WorkflowError(f"refusing generated-file symlink: {name}")
        if not p.exists() or p.read_text(encoding="utf-8") != text:
            p.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=".generated-", dir=p.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as out:
                    out.write(text)
                    out.flush()
                    os.fsync(out.fileno())
                os.replace(temporary, p)
            finally:
                Path(temporary).unlink(missing_ok=True)
            changed.append(name)
    return changed


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def github_json(path: str) -> dict[str, Any]:
    # Exact origin and no redirects; never transmits local credentials or source.
    request = Request("https://api.github.com/repos/" + path,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "Human2API-release-check"})
    with build_opener(_NoRedirect()).open(request, timeout=12) as response:
        raw = response.read(4_000_001)
    if len(raw) > 4_000_000:
        raise WorkflowError("GitHub response exceeded bounded size")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise WorkflowError("unexpected GitHub response")
    return value


def hosted_ci(root: Path, repository: str) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise WorkflowError("repository must have owner/name form")
    head = github_json(repository + "/git/ref/heads/main")["object"]["sha"]
    tree = github_json(repository + "/git/trees/" + head + "?recursive=1")
    if tree.get("truncated"):
        raise WorkflowError("remote source tree is incomplete")
    blobs = {x["path"]: x["sha"] for x in tree["tree"] if x["type"] == "blob"}
    for folder in ("src", "android-companion", "scripts", "tests", ".github"):
        for p in (root / folder).rglob("*"):
            if not p.is_file() or p.is_symlink() or any(x in {"__pycache__", "build", ".gradle"} or x.endswith(".egg-info") for x in p.parts):
                continue
            raw = p.read_bytes()
            sha = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
            if blobs.get(p.relative_to(root).as_posix()) != sha:
                return {"status": "blocked", "detail": "local source differs from published main", "revision": head}
    package_metadata = (root / "pyproject.toml").read_bytes()
    metadata_sha = hashlib.sha1(b"blob " + str(len(package_metadata)).encode() + b"\0" + package_metadata).hexdigest()
    if blobs.get("pyproject.toml") != metadata_sha:
        return {"status": "blocked", "detail": "package metadata differs from published main", "revision": head}
    runs = github_json(repository + "/actions/runs?head_sha=" + head + "&per_page=100")["workflow_runs"]
    required = {"CI", "CodeQL", "GitHub Pages", "Native builds", "Android build"}
    latest = {}
    for run in runs:
        if run["name"] in required and run.get("event") in {"push", "workflow_dispatch"} and run["name"] not in latest:
            latest[run["name"]] = run.get("conclusion")
    ok = required.issubset(latest) and all(latest[x] == "success" for x in required)
    return {"status": "passed" if ok else "blocked", "detail": "all required hosted workflows passed for matching source" if ok
        else "hosted workflows missing or not successful; inspect annotations (account billing lock previously confirmed)",
        "revision": head, "workflows": latest}


class ReleaseSession:
    def __init__(self, root: Path, output: Path):
        self.root, self.output = root.resolve(), output.resolve()
        if not (self.root / "src/human2api/__init__.py").is_file():
            raise WorkflowError("complete requires the Human2API source checkout (--root)")
        if output.is_symlink():
            raise WorkflowError("report directory must not be a symlink")
        self.output.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            self.output.chmod(0o700)
        self.checks: list[dict[str, Any]] = []
        self.env = dict(os.environ, PYTHONPATH=str(self.root / "src"), PYTHONUTF8="1", PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_NO_INPUT="1")

    def record(self, name: str, status: str, detail: str, **evidence: Any) -> dict[str, Any]:
        result = {"name": name, "status": status, "detail": detail, **evidence}
        self.checks.append(result)
        print(f"[{status.upper()}] {name}: {detail}", flush=True)
        return result

    def command(self, name: str, argv: list[str], *, timeout: int = 600,
                cwd: Path | None = None, env: dict[str, str] | None = None,
                blocked_codes: tuple[int, ...] = ()) -> dict[str, Any]:
        logfile = self.output / f"{len(self.checks):02d}-{name}.log"
        start = time.monotonic()
        fd = os.open(logfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        process = None
        with os.fdopen(fd, "wb") as log:
            try:
                process = subprocess.Popen(argv, cwd=cwd or self.root, env=env or self.env,
                    stdout=log, stderr=subprocess.STDOUT, start_new_session=os.name != "nt")
                rc = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                if os.name != "nt":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
                process.wait()
                return self.record(name, "failed", "command timed out", log=logfile.name)
            except OSError as exc:
                return self.record(name, "blocked", type(exc).__name__, log=logfile.name)
        return self.record(name, "passed" if rc == 0 else "blocked" if rc in blocked_codes else "failed", f"exit {rc}",
                           log=logfile.name, seconds=round(time.monotonic()-start, 2))

    def acceptance(self, evidence_dir: Path | None) -> None:
        digest = source_digest(self.root)
        for target in PLATFORMS:
            path = (evidence_dir / f"{target}.json") if evidence_dir else None
            try:
                data = json.loads(path.read_text(encoding="utf-8")) if path else {}
                valid = (data.get("sourceDigest") == digest and data.get("target") == target
                    and data.get("status") == "passed" and data.get("simulated") is False
                    and data.get("verificationAssertions", 0) > 0)
                self.record(target, "passed" if valid else "blocked",
                    "matching operator acceptance receipt (not independent attestation)" if valid
                    else "real-device acceptance receipt missing or not bound to this source")
            except (OSError, ValueError, TypeError):
                self.record(target, "blocked", "cannot validate device acceptance receipt")

    def finish(self, *, scope: str) -> dict[str, Any]:
        passed = bool(self.checks) and all(x["status"] == "passed" for x in self.checks)
        result = {"version": __version__, "scope": scope,
            "status": "passed" if passed else "blocked" if not any(x["status"]=="failed" for x in self.checks) else "failed",
            "releaseReady": passed and scope == "release", "sourceDigest": source_digest(self.root),
            "platform": platform.platform(), "checks": self.checks,
            "notes": "Local checks never establish hosted CI, device compatibility, or verified publisher identity."}
        path = self.output / "report.json"
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"Report: {path}", flush=True)
        return result


def complete(root: Path, *, output: Path | None = None, repair: bool = False,
             bootstrap: bool = False, native: bool = False, android: bool = False,
             local_only: bool = False, evidence_dir: Path | None = None,
             repository: str = "karemfree1282-gif/human2api") -> dict[str, Any]:
    output = output or root / ".h2a" / "checks" / (time.strftime("%Y%m%d-%H%M%S") + "-" + os.urandom(3).hex())
    s = ReleaseSession(root, output)
    if repair:
        changed = repair_generated(s.root)
        s.record("generated-repair", "passed", f"repaired {len(changed)} generated files", files=changed)
    if bootstrap:
        s.command("dependencies", [sys.executable, "-m", "pip", "install", "-e", ".[dev,vault,signing]"], timeout=1200)
        s.command("browser-install", [sys.executable, "-m", "playwright", "install", "chromium"], timeout=600)
        if native:
            packages = [".[studio,desktop,accessibility,vault,signing]", "pyinstaller>=6.16,<7"]
            if sys.platform.startswith("linux"):
                packages.append("PySide6>=6.8,<7")
            s.command("native-dependencies", [sys.executable, "-m", "pip", "install", *packages], timeout=1200)
    s.command("compile", [sys.executable, "-m", "compileall", "-q", "src", "scripts"])
    try:
        for path in sorted((s.root / "workflows").glob("*.json")):
            load_workflow(path)
        expected = json.loads((s.root / "schemas/workflow.schema.json").read_text(encoding="utf-8"))
        if expected != workflow_schema():
            raise WorkflowError("schema drift; run complete --repair")
        s.record("workflows-and-schema", "passed", "examples and executable contract agree")
    except (WorkflowError, OSError, ValueError) as exc:
        s.record("workflows-and-schema", "failed", str(exc)[:300])
    if shutil.which("node"):
        for path in sorted((s.root / "src/human2api/static").glob("*.js")):
            s.command("javascript-" + path.stem, ["node", "--check", str(path)])
    else:
        s.record("javascript", "blocked", "Node.js required for syntax checks")
    junit = s.output / "pytest.xml"
    check = s.command("tests", [sys.executable, "-m", "pytest", "-q", f"--junitxml={junit}"], timeout=1200)
    try:
        counts = junit_summary(junit)
        check["counts"] = counts
        if counts["skipped"] or counts["tests"] == 0:
            check.update(status="blocked" if check["status"] == "passed" else check["status"],
                         detail="not all tests executed; skipped/empty suite does not establish a pass")
            print(f"[{check['status'].upper()}] tests: {counts['passed']} passed, {counts['skipped']} skipped; release gate remains closed", flush=True)
    except (OSError, ET.ParseError):
        check.update(status="failed", detail="test runner produced no valid JUnit evidence")
    dist = s.output / "dist"
    build = s.command("wheel", [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "--no-build-isolation", "-w", str(dist)])
    if build["status"] == "passed":
        wheels = list(dist.glob("human2api-*.whl"))
        if len(wheels) != 1:
            s.record("installed-smoke", "failed", "build did not produce exactly one wheel")
        else:
            with tempfile.TemporaryDirectory(prefix="h2a-install-") as tmp:
                temp = Path(tmp)
                installed = s.command("isolated-install", [sys.executable, "-m", "pip", "install", "--no-deps", "--target", str(temp / "lib"), str(wheels[0])])
                if installed["status"] == "passed":
                    env = dict(os.environ, PYTHONPATH=str(temp / "lib"), PYTHONUTF8="1", PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_NO_INPUT="1")
                    code = ("from pathlib import Path;from human2api.cli import main;"
                            "assert main(['init'])==0;assert main(['check','create_invoice'])==0;"
                            "assert main(['--version'])==0")
                    # --version intentionally exits via argparse; use it separately.
                    s.command("installed-smoke", [sys.executable, "-c", code], cwd=temp, env=env)
            build["sha256"] = hashlib.sha256(wheels[0].read_bytes()).hexdigest()
    if native:
        s.command("native-build", [sys.executable, "scripts/build_native.py", "--output", str(s.output / "native")], timeout=1200, blocked_codes=(2,))
    if android:
        s.command("android-build", [sys.executable, "scripts/build_android.py", "--output", str(s.output / "android")], timeout=1200, blocked_codes=(2,))
    if not local_only:
        s.acceptance(evidence_dir)
        if not native:
            s.record("native-distributions", "blocked", "build and test native installers on each target OS")
        if not android:
            s.record("android-distribution", "blocked", "Android build and real-device acceptance required")
        try:
            ci = hosted_ci(s.root, repository)
            s.record("hosted-ci", **ci)
        except (OSError, ValueError, KeyError, WorkflowError) as exc:
            s.record("hosted-ci", "blocked", f"cannot verify hosted CI ({type(exc).__name__}); no success assumed")
        try:
            receipt = json.loads((evidence_dir / "registry-deployment.json").read_text(encoding="utf-8")) if evidence_dir else {}
            good = receipt.get("sourceDigest") == source_digest(s.root) and receipt.get("httpsVerified") is True and receipt.get("backupRestoreVerified") is True and receipt.get("publisherLifecycleVerified") is True
            s.record("public-registry", "passed" if good else "blocked", "operator deployment acceptance receipt (not independent attestation)" if good else "HTTPS hosting, publisher lifecycle and backup/restore acceptance required")
        except (OSError, TypeError, ValueError):
            s.record("public-registry", "blocked", "invalid deployment receipt")
    return s.finish(scope="local" if local_only else "release")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path.cwd())
    p.add_argument("--output", type=Path)
    p.add_argument("--repair", action="store_true")
    p.add_argument("--bootstrap", action="store_true")
    p.add_argument("--native", action="store_true")
    p.add_argument("--android", action="store_true")
    p.add_argument("--local-only", action="store_true")
    p.add_argument("--evidence-dir", type=Path)
    p.add_argument("--repository", default="karemfree1282-gif/human2api")
    a = p.parse_args(argv)
    try:
        report = complete(**vars(a))
        return 0 if report["status"] == "passed" else 2
    except (WorkflowError, OSError, ValueError) as exc:
        print(f"Completion error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
