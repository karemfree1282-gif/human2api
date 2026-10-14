#!/usr/bin/env python3
"""Entry point script for `python scripts/complete.py`."""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from human2api.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(["complete"] + sys.argv[1:]))
