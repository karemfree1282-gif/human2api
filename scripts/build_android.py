#!/usr/bin/env python3
"""Build the real Android debug APK with the SDK and a verified Gradle distribution.

No placeholder APK is generated. Requires Android SDK API 34 and Java 17+.
If Gradle is missing, securely bootstraps official Gradle 8.7 on first use.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
ANDROID_DIR = ROOT / "android-companion"
GRADLE_VERSION = "8.7"
GRADLE_URL = f"https://services.gradle.org/distributions/gradle-{GRADLE_VERSION}-bin.zip"
GRADLE_SHA256 = "544c35d6bd849ae8a5ed0bcea39ba677dc40f49df7d1835561582da2009b961d"


def sdk_path() -> pathlib.Path | None:
    candidates = [os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT")]
    home = pathlib.Path.home()
    candidates += [
        str(home / "AppData/Local/Android/Sdk"),
        str(home / "Library/Android/sdk"),
        str(home / "Android/Sdk"),
        "/opt/android-sdk",
    ]
    for candidate in candidates:
        if candidate and (pathlib.Path(candidate) / "platforms/android-34/android.jar").is_file():
            return pathlib.Path(candidate)
    return None


def get_gradle() -> str:
    in_path = shutil.which("gradle")
    if in_path:
        return in_path
    cached_root = pathlib.Path.home() / ".cache/human2api" / f"gradle-{GRADLE_VERSION}"
    executable = cached_root / "bin" / ("gradle.bat" if os.name == "nt" else "gradle")
    if executable.is_file():
        return str(executable)
    if os.environ.get("H2A_NO_DOWNLOAD") == "1":
        raise RuntimeError("Gradle not installed and H2A_NO_DOWNLOAD=1. Install Gradle 8.7.")
    archive = cached_root.parent / f"gradle-{GRADLE_VERSION}-bin.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        print("Downloading official Gradle 8.7 (once, around 128 MB)...", flush=True)
        temp = archive.with_suffix(".part")
        try:
            with urllib.request.urlopen(GRADLE_URL, timeout=60) as response, temp.open("wb") as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    if output.tell() > 210 * 1024 * 1024:
                        raise RuntimeError("Gradle archive exceeds safe size limit")
            temp.replace(archive)
        finally:
            temp.unlink(missing_ok=True)
    with archive.open("rb") as f:
        digest = hashlib.file_digest(f, "sha256").hexdigest()
    if digest != GRADLE_SHA256:
        archive.unlink(missing_ok=True)
        raise RuntimeError("Gradle download SHA256 mismatch; archive rejected")
    with zipfile.ZipFile(archive) as zipped:
        for member in zipped.infolist():
            target = (cached_root.parent / member.filename).resolve()
            if not target.is_relative_to(cached_root.parent.resolve()):
                raise RuntimeError("Unsafe archive path in Gradle distribution")
            if member.file_size > 80 * 1024 * 1024:
                raise RuntimeError("Unexpectedly large Gradle archive member")
        zipped.extractall(cached_root.parent)
    if not executable.is_file():
        raise RuntimeError("Gradle executable missing from extracted distribution")
    if os.name != "nt":
        executable.chmod(executable.stat().st_mode | 0o111)
    return str(executable)


def main() -> int:
    sdk = sdk_path()
    if sdk is None:
        print(json.dumps({
            "status": "blocked",
            "reason": "Android SDK Platform 34 not found. Install Android Studio, Android SDK Platform 34 and Android SDK Build Tools 34.0.0 first.",
            "android_home": os.environ.get("ANDROID_HOME"),
        }, indent=2))
        return 2
    java_home = os.environ.get("JAVA_HOME")
    if not shutil.which("java") and not java_home:
        candidates = [
            pathlib.Path("C:/Program Files/Android/Android Studio/jbr"),
            pathlib.Path("C:/Program Files/Android/Android Studio/jre"),
        ]
        java_home = next((str(p) for p in candidates if (p / "bin" / "java.exe").is_file()), None)
    if not shutil.which("java") and not java_home:
        print(json.dumps({"status": "blocked", "reason": "Java 17+ JDK is required. Android Studio bundles one; set JAVA_HOME to the Android Studio jbr directory."}, indent=2))
        return 2
    try:
        gradle = get_gradle()
    except (RuntimeError, OSError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, indent=2))
        return 2
    cmd = [gradle, "assembleDebug", "--no-daemon"]
    try:
        proc = subprocess.run(cmd, cwd=str(ANDROID_DIR), capture_output=True, text=True,
                              timeout=600, env={**os.environ, "ANDROID_HOME": str(sdk), **({"JAVA_HOME": java_home} if java_home else {})})
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, indent=2))
        return 1
    if proc.returncode != 0:
        print(json.dumps({"status": "failed", "stderr": proc.stderr[-4000:], "stdout": proc.stdout[-4000:]}, indent=2))
        return 1
    apk = ANDROID_DIR / "app/build/outputs/apk/debug/app-debug.apk"
    if not apk.is_file():
        print(json.dumps({"status": "failed", "reason": "Gradle completed but the expected APK does not exist"}, indent=2))
        return 1
    with apk.open("rb") as f:
        digest = hashlib.file_digest(f, "sha256").hexdigest()
    print(json.dumps({"status": "passed", "apk": str(apk), "size": apk.stat().st_size,
                      "sha256": digest}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
