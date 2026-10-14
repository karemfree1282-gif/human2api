#!/usr/bin/env python3
"""Cross-platform Native Distribution Builder (`scripts/build_native.py`)."""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from human2api.completion import build_distributions_and_smoke_test  # noqa: E402


def main() -> int:
    dist_dir = ROOT / "dist"
    results = build_distributions_and_smoke_test(ROOT, dist_dir)
    failed = [r for r in results if r.status == "failed"]
    for r in results:
        print(f"[{r.status.upper()}] {r.name}: {r.details}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
