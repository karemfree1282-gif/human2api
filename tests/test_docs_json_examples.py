"""README and documentation JSON examples must be copy/paste valid."""
from __future__ import annotations

import json
import re
from pathlib import Path


def test_documentation_json_fences_parse():
    root = Path(__file__).resolve().parents[1]
    documents = [root / 'README.md', *(root / 'docs').rglob('*.md')]
    checked = 0
    for document in documents:
        text = document.read_text(encoding='utf-8')
        for example in re.findall(r'^\`\`\`json\\s*\\n(.*?)^\`\`\`\\s*$', text, re.MULTILINE | re.DOTALL):
            try:
                json.loads(example)
            except json.JSONDecodeError as exc:
                raise AssertionError(f'Invalid JSON example in {document.relative_to(root)}: {exc}') from exc
            checked += 1
    assert checked >= 2, 'Expected documentation examples are missing'
