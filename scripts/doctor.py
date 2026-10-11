#!/usr/bin/env python3
"""Local, read-only diagnostics for Human2API without network access."""
from __future__ import annotations

import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from human2api.models import list_workflows  # noqa: E402


def main() -> int:
    print('Human2API project diagnostics')
    print('Python:', platform.python_version())
    if sys.version_info < (3, 10):
        print('FAIL: Python 3.10 or newer is required')
        return 1
    try:
        import playwright  # noqa: F401
        print('Playwright: import available')
    except ImportError:
        print('FAIL: Python Playwright package is missing')
        return 1
    workflows = list_workflows(ROOT / 'workflows')
    if not workflows:
        print('FAIL: no valid example workflows')
        return 1
    print('Example workflows:', ', '.join(x['name'] for x in workflows))
    for path in ('LICENSE', 'README.md', 'SECURITY.md', 'docs/index.html', '.github/workflows/ci.yml'):
        if not (ROOT / path).is_file():
            print('FAIL: missing', path)
            return 1
    print('Files and workflow format: OK')
    print('Note: this does not verify Chromium launch, full browser tests or GitHub publishing.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
