"""Safe local first-run workflow that does not depend on external services."""

from __future__ import annotations

from urllib.parse import urlparse

from human2api.models import Workflow
from human2api.workspace import Workspace


def ensure_local_demo(workspace: Workspace, base_url: str) -> Workflow:
    """Seed a small, explicit-consent invoice demo without replacing user data."""
    demo_file = workspace.workflows_dir / "demo_invoice.json"
    if demo_file.exists():
        wf = Workflow.load(demo_file)
        # The local port may change on every launch. Only repair the URL of
        # our known demo; never overwrite custom workflows or user steps.
        if wf.name == "Demo Invoice" and wf.steps and wf.steps[0].action == "goto":
            previous = urlparse(wf.steps[0].url or "")
            if previous.hostname in {"127.0.0.1", "127.0.0.2", "localhost", "::1"} and previous.path == "/demo":
                wf.steps[0].url = f"{base_url}/demo"
                wf.allowedHosts = list(dict.fromkeys([*wf.allowedHosts, urlparse(base_url).hostname]))
                wf.save(demo_file)
        return wf
    host = urlparse(base_url).hostname
    if host not in {"127.0.0.1", "127.0.0.2", "localhost", "::1"}:
        raise ValueError("Demo workflow requires a local loopback server")
    wf = Workflow.from_dict({
        "schemaVersion": "0.5",
        "name": "Demo Invoice",
        "target": "browser",
        "mode": "write",
        "networkPolicy": "strict",
        "allowedHosts": [host],
        "inputs": {
            "customer": {"type": "string", "required": True, "default": "شركة المستقبل"},
            "amount": {"type": "string", "required": True, "default": "250"},
        },
        "steps": [
            {"action": "goto", "url": f"{base_url}/demo"},
            {"action": "type", "selector": "#customer-name", "text": "${input:customer}", "isWriteAction": True},
            {"action": "type", "selector": "#invoice-amount", "text": "${input:amount}", "isWriteAction": True},
            {"action": "click", "selector": "#submit-invoice-btn", "isWriteAction": True, "idempotent": False},
            {"action": "assert_text", "selector": "#invoice-result", "expected": "${input:customer}", "match": "contains"},
        ],
    })
    wf.save(demo_file)
    return wf
