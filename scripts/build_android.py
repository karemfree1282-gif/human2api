#!/usr/bin/env python3
"""Android Companion APK Builder (`scripts/build_android.py`).
Executes a real Gradle APK build when Android SDK + Gradle are installed, and reports honestly when blocked by missing SDK.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
ANDROID_DIR = ROOT / "android-companion"


def main() -> int:
    gradle = shutil.which("gradle") or (str(ANDROID_DIR / "gradlew") if (ANDROID_DIR / "gradlew").exists() else None)
    sdk_root = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if not gradle or not sdk_root:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "reason": "Android SDK (ANDROID_HOME) or Gradle is not installed on this machine. No fake APK was generated.",
                    "gradle_found": bool(gradle),
                    "android_sdk_found": bool(sdk_root),
                },
                indent=2,
            )
        )
        return 2

    cmd = [gradle, "assembleDebug", "--no-daemon"]
    proc = subprocess.run(cmd, cwd=str(ANDROID_DIR), capture_output=True, text=True)
    if proc.returncode != 0:
        print(json.dumps({"status": "failed", "stderr": proc.stderr[-1000:]}, indent=2))
        return 1

    apks = list(ANDROID_DIR.rglob("*.apk"))
    if not apks:
        print(json.dumps({"status": "failed", "reason": "Gradle succeeded but no APK file found."}, indent=2))
        return 1

    apk = apks[0]
    sha256 = hashlib.sha256(apk.read_bytes()).hexdigest()
    print(json.dumps({"status": "passed", "apk": str(apk), "sha256": sha256}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
