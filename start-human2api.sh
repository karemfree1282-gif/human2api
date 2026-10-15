#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
  echo 'Python 3.10 or later is required.' >&2
  exit 1
fi
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install -e '.[browser]'
.venv/bin/python -m playwright install chromium || echo 'Playwright Chromium download unavailable; an existing system browser may work.' >&2
exec .venv/bin/python -m human2api start --dir "${HOME}/Human2API-Workspace"
