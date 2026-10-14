#!/usr/bin/env python3
"""GitHub Repository Publisher & Sync Helper (`scripts/publish_github.py`)."""

from __future__ import annotations

import shutil
import subprocess
import sys

REPO_SLUG = "karemfree1282-gif/human2api"
REPO_URL = f"https://github.com/{REPO_SLUG}.git"


def main() -> int:
    git_bin = shutil.which("git")
    if not git_bin:
        print("Error: git is not installed.", file=sys.stderr)
        return 1
    print(f"Preparing to push verified main and tags to {REPO_URL}...")
    remotes = subprocess.run([git_bin, "remote"], capture_output=True, text=True).stdout.splitlines()
    if "origin" not in remotes:
        subprocess.run([git_bin, "remote", "add", "origin", REPO_URL], check=False)
    res = subprocess.run([git_bin, "push", "-u", "origin", "main", "--tags"])
    return res.returncode


if __name__ == "__main__":
    sys.exit(main())
