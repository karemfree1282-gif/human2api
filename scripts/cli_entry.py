"""Frozen console/MCP entry, including bundled Playwright browser discovery."""
import os
import sys
from pathlib import Path
if getattr(sys, "frozen", False):
    browser = Path(sys._MEIPASS) / "playwright/driver/package/.local-browsers"
    if browser.is_dir():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browser)
if __name__ == "__main__":
    from human2api.cli import main
    if len(sys.argv) > 1 and sys.argv[1] == "--h2a-cli":
        del sys.argv[1]
    raise SystemExit(main())
