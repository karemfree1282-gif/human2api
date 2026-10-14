"""Desktop & Web Studio launcher for Human2API."""

from __future__ import annotations

import pathlib
from typing import Optional

from human2api.http_server import Human2APIServer
from human2api.workspace import Workspace


def launch_studio_server(
    workspace_dir: Optional[pathlib.Path] = None,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> Human2APIServer:
    ws = Workspace(workspace_dir)
    server = Human2APIServer(workspace=ws, host=host, port=port)
    server.start()
    return server
