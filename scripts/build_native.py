"""Build native portable Studio and CLI on the current OS, never cross-claim.

Install build dependencies explicitly first:
pip install -e '.[studio,desktop,accessibility,vault,signing]' pyinstaller
On Linux also install PySide6 and the distro AT-SPI binding for native selectors.
--bundle-browser downloads Chromium through Playwright before freezing.
Artifacts are unsigned; OS signing/notarization requires owner-managed identities.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class BuildBlocked(RuntimeError):
    """Required external build tools are not installed."""


def build(output: Path, bundle_browser: bool = False) -> dict:
    if importlib.util.find_spec("PyInstaller") is None or importlib.util.find_spec("webview") is None:
        raise BuildBlocked("native build requires PyInstaller and human2api[studio,desktop,accessibility,vault,signing]")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    if sys.platform.startswith("linux") and Path("/usr/lib/python3/dist-packages").is_dir():
        env["PYTHONPATH"] += os.pathsep + "/usr/lib/python3/dist-packages"
    if bundle_browser:
        env["PLAYWRIGHT_BROWSERS_PATH"] = "0"
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], env=env, check=True, timeout=900)
    dist, work = output / "app", output / "work"
    for name, script, windowed in (("h2a", "cli_entry.py", False), ("Human2API-Studio", "studio_entry.py", True)):
        command = [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", "--onedir",
            "--name", name, "--paths", str(ROOT / "src"), "--collect-all", "human2api",
            "--collect-all", "playwright", "--collect-all", "webview", "--hidden-import", "cryptography",
            "--distpath", str(dist), "--workpath", str(work / name), "--specpath", str(work)]
        if sys.platform == "darwin":
            command += ["--hidden-import", "ApplicationServices", "--hidden-import", "AppKit"]
        elif sys.platform == "win32":
            command += ["--collect-all", "pywinauto"]
        else:
            command += ["--hidden-import", "pyatspi", "--collect-all", "PySide6"]
        if windowed:
            command.append("--windowed")
        subprocess.run(command + [str(ROOT / "scripts" / script)], cwd=ROOT, env=env, check=True, timeout=1200)
    cli = dist / "h2a" / ("h2a.exe" if os.name == "nt" else "h2a")
    subprocess.run([str(cli), "--version"], check=True, timeout=30)
    from human2api import __version__
    from human2api.completion import source_digest
    base = output / f"Human2API-{__version__}-{platform.system().lower()}-{platform.machine().lower()}"
    archive = Path(shutil.make_archive(str(base), "zip" if os.name == "nt" else "gztar", dist))
    artifacts = [archive]
    if sys.platform == "darwin":
        dmg = base.with_suffix(".dmg")
        subprocess.run(["hdiutil", "create", "-volname", "Human2API", "-srcfolder", str(dist), "-ov", "-format", "UDZO", str(dmg)], check=True, timeout=300)
        artifacts.append(dmg)
    elif os.name == "nt":
        compiler = shutil.which("makensis") or str(Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "NSIS/makensis.exe")
        if Path(compiler).is_file():
            setup = base.with_name(base.name + "-setup.exe")
            subprocess.run([compiler, f"/DAPPDIR={dist}", f"/DOUTFILE={setup}", str(ROOT / "packaging/windows.nsi")], check=True, timeout=180)
            artifacts.append(setup)
    report = {"version": __version__, "sourceDigest": source_digest(ROOT), "os": platform.system(),
        "architecture": platform.machine(), "cliSmokePassed": True, "signed": False, "deviceAcceptance": False,
        "artifacts": [{"name": x.name, "sha256": hashlib.sha256(x.read_bytes()).hexdigest()} for x in artifacts]}
    (output / "native-build.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, default=ROOT / "dist/native")
    p.add_argument("--bundle-browser", action="store_true")
    args = p.parse_args()
    try:
        print(json.dumps(build(args.output, args.bundle_browser), indent=2))
    except BuildBlocked as exc:
        print(f"Native build blocked: {exc}", file=sys.stderr)
        raise SystemExit(2)
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f"Native build failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
