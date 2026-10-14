"""Workspace initialization, configuration, and batch workflow execution helpers."""

from __future__ import annotations

import json
import pathlib
from typing import Any, Dict, List, Optional

from human2api.history import RunHistoryJournal
from human2api.marketplace import MarketplaceManager
from human2api.models import Workflow
from human2api.registry import ToolRegistry
from human2api.scheduler import WorkflowScheduler
from human2api.vault import SecretVault


class Workspace:
    """Manages local `.h2a` state directory, workflows, vault, history, scheduler, and marketplace."""

    def __init__(self, root_dir: Optional[pathlib.Path] = None) -> None:
        self.root_dir = (pathlib.Path(root_dir) if root_dir else pathlib.Path.cwd()).resolve()
        self.state_dir = self.root_dir / ".h2a"
        self.workflows_dir = self.root_dir / "workflows"
        self.packages_dir = self.state_dir / "packages"
        self.uploads_dir = self.root_dir / "uploads"
        self.downloads_dir = self.root_dir / "downloads"
        self.config_file = self.state_dir / "config.json"

        self.vault = SecretVault(self.state_dir / "vault.json")
        self.history = RunHistoryJournal(self.state_dir / "history.json")
        self.registry = ToolRegistry(self.state_dir / "registry.sqlite3")
        self.marketplace = MarketplaceManager(self.packages_dir, registry=self.registry)
        self.scheduler = WorkflowScheduler(self.state_dir / "schedules.json")

    def initialize(self) -> Dict[str, str]:
        for d in (self.state_dir, self.workflows_dir, self.packages_dir, self.uploads_dir, self.downloads_dir):
            d.mkdir(parents=True, exist_ok=True)
        if not self.config_file.exists():
            default_cfg = {
                "version": "0.5.0",
                "defaultTarget": "browser",
                "networkPolicy": "strict",
                "allowWriteByDefault": False,
                "aiHealingConsent": False,
                "aiProvider": "none",
                "language": "ar",
                "theme": "dark",
            }
            self.config_file.write_text(json.dumps(default_cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {
            "root_dir": str(self.root_dir),
            "state_dir": str(self.state_dir),
            "workflows_dir": str(self.workflows_dir),
        }

    def get_config(self) -> Dict[str, Any]:
        if not self.config_file.exists():
            self.initialize()
        return json.loads(self.config_file.read_text(encoding="utf-8"))

    def update_config(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        cfg = self.get_config()
        cfg.update(updates)
        self.config_file.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return cfg

    def list_workflows(self) -> List[Dict[str, Any]]:
        self.workflows_dir.mkdir(parents=True, exist_ok=True)
        out: List[Dict[str, Any]] = []
        for p in sorted(self.workflows_dir.glob("*.json")):
            try:
                wf = Workflow.load(p)
                d = wf.to_dict()
                d["filename"] = p.name
                out.append(d)
            except Exception:
                continue
        return out
