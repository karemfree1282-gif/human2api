"""Run from a source checkout: python scripts/complete.py --repair."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from human2api.completion import main
if __name__ == "__main__":
    raise SystemExit(main())
