"""Build and lint the companion using installed JDK 17+, Gradle 8.11.1 and SDK 35.

This command does not accept SDK licenses on behalf of the operator. The debug
APK is for testing only. Release signing keys never belong in this repository.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]


class BuildBlocked(RuntimeError):
    """Required external build tools are not installed."""


def build(output: Path) -> dict:
    gradle = shutil.which("gradle")
    sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if not gradle or not shutil.which("java") or not sdk or not (Path(sdk) / "platforms/android-35/android.jar").is_file():
        raise BuildBlocked("Install JDK 17+, Gradle 8.11.1 and licensed Android SDK platform 35 first")
    subprocess.run([gradle, "--no-daemon", "--console=plain", "assembleDebug", "lintDebug", "testDebugUnitTest"],
                   cwd=ROOT / "android-companion", check=True, timeout=1200)
    apk = ROOT / "android-companion/app/build/outputs/apk/debug/app-debug.apk"
    if not apk.is_file():
        raise RuntimeError("Gradle produced no APK")
    output = output.resolve(); output.mkdir(parents=True, exist_ok=True)
    target = output / "Human2API-Companion-debug.apk"
    shutil.copy2(apk, target)
    sys.path.insert(0, str(ROOT / "src"))
    from human2api.completion import source_digest
    report = {"sourceDigest": source_digest(ROOT), "apk": target.name,
              "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "signing": "debug-only", "deviceAcceptance": False}
    (output / "android-build.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, default=ROOT / "dist/android")
    try:
        print(json.dumps(build(p.parse_args().output), indent=2))
    except BuildBlocked as exc:
        print(f"Android build blocked: {exc}", file=sys.stderr)
        raise SystemExit(2)
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f"Android build failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
