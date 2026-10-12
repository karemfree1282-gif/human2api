"""Initialize a workspace from packaged examples without overwriting user files."""
from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

from .models import save_workflow


def initialize(directory: Path, *, port: int = 8765) -> list[str]:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    created = []
    for resource in files("human2api").joinpath("examples").iterdir():
        if resource.name.endswith(".json"):
            destination = directory / resource.name
            if destination.exists() or destination.is_symlink():
                continue
            data = json.loads(resource.read_text(encoding="utf-8"))
            if data["name"] == "create_invoice":
                data["startUrl"] = f"http://127.0.0.1:{port}/demo"
            save_workflow(destination, data)
            created.append(data["name"])
    return created
