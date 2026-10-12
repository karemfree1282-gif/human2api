"""Frozen Studio entry; an explicit worker mode is used for browser recording."""
import os
import sys
from pathlib import Path
if getattr(sys, "frozen", False):
    browser = Path(sys._MEIPASS) / "playwright/driver/package/.local-browsers"
    if browser.is_dir():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browser)
for stream in ("stdout", "stderr"):
    if getattr(sys, stream) is None:
        setattr(sys, stream, open(os.devnull, "w", encoding="utf-8"))
if __name__ == "__main__":
    if sys.argv[1:2] == ["--h2a-cli"]:
        from human2api.cli import main
        raise SystemExit(main(sys.argv[2:]))
    from human2api.studio import start
    start(Path.home() / "Human2API" / "workflows")
