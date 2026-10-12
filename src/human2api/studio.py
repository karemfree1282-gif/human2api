"""Native desktop window hosting the authenticated loopback studio.

The optional pywebview extra supplies the operating system's webview. There is
no JS-to-Python command bridge and no arbitrary process execution endpoint.
"""
from __future__ import annotations

import threading
import os
import sys
from pathlib import Path

from .http_server import make_server
from .models import WorkflowError
from .workspace import initialize


def start(directory: Path) -> None:
    try:
        import webview
    except ImportError as exc:
        raise WorkflowError("native studio needs: pip install 'human2api[studio]'") from exc
    server = make_server(directory, port=0)
    if not any(directory.glob("*.json")):
        initialize(directory, port=server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        webview.create_window("Human2API Studio", f"http://127.0.0.1:{server.server_address[1]}",
                              width=1320, height=860, min_size=(900, 600))
        webview.start(debug=False, gui=os.environ.get("H2A_WEBVIEW_GUI") or ("qt" if sys.platform.startswith("linux") else None))
    finally:
        with server.lock:
            for event in server.cancellations.values():
                event.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
