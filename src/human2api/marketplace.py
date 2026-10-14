"""Marketplace Client for Installing, Pinning, Verifying, and Updating Signed Human2API Packages."""

from __future__ import annotations

import json
import pathlib
from typing import Any, Dict, List, Optional

from human2api.models import Workflow
from human2api.registry import ToolRegistry
from human2api.trust import UntrustedPackageError, unpack_and_verify_package_zip


class MarketplaceManager:
    """Manages local installation, publisher key pinning, signature verification, and safe upgrades of Marketplace tools."""

    def __init__(self, install_dir: pathlib.Path, registry: Optional[ToolRegistry] = None) -> None:
        self.install_dir = pathlib.Path(install_dir)
        self.install_dir.mkdir(parents=True, exist_ok=True)
        self.pins_file = self.install_dir / "pinned_publishers.json"
        self.installed_index_file = self.install_dir / "installed_packages.json"
        self.registry = registry

    def _load_pins(self) -> Dict[str, str]:
        if not self.pins_file.exists():
            return {}
        return json.loads(self.pins_file.read_text(encoding="utf-8"))

    def _save_pins(self, pins: Dict[str, str]) -> None:
        self.pins_file.write_text(json.dumps(pins, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _load_installed(self) -> Dict[str, Dict[str, Any]]:
        if not self.installed_index_file.exists():
            return {}
        return json.loads(self.installed_index_file.read_text(encoding="utf-8"))

    def _save_installed(self, data: Dict[str, Dict[str, Any]]) -> None:
        self.installed_index_file.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def pin_publisher_key(self, publisher_id: str, public_key_b64: str) -> None:
        pins = self._load_pins()
        pins[publisher_id] = public_key_b64
        self._save_pins(pins)

    def install_from_bytes(
        self,
        zip_bytes: bytes,
        expected_publisher_key: Optional[str] = None,
        allow_privilege_expansion: bool = False,
    ) -> Dict[str, Any]:
        pins = self._load_pins()
        # First unpack and verify internal signature
        manifest, wf = unpack_and_verify_package_zip(zip_bytes, trusted_public_key_b64=expected_publisher_key)
        pub_id = str(manifest["publisher_id"])
        pub_key = str(manifest["public_key"])
        tool_id = str(manifest["tool_id"])
        version = str(manifest["version"])

        if pub_id in pins and pins[pub_id] != pub_key:
            raise UntrustedPackageError(
                f"Publisher {pub_id!r} key mismatch against pinned key! Refusing installation."
            )
        # Pin publisher key on first verified install (TOFU + explicit pin check)
        if pub_id not in pins:
            pins[pub_id] = pub_key
            self._save_pins(pins)

        installed = self._load_installed()
        if tool_id in installed:
            prev = installed[tool_id]
            if prev["publisher_id"] != pub_id:
                raise UntrustedPackageError(f"Tool {tool_id!r} publisher changed from {prev['publisher_id']} to {pub_id}!")
            prev_wf = Workflow.load(self.install_dir / f"{tool_id}.workflow.json")
            if not allow_privilege_expansion:
                new_hosts = set(wf.allowedHosts) - set(prev_wf.allowedHosts)
                new_apps = set(wf.allowedApps) - set(prev_wf.allowedApps)
                new_pkgs = set(wf.allowedPackages) - set(prev_wf.allowedPackages)
                mode_escalated = prev_wf.mode == "read" and wf.mode == "write"
                if new_hosts or new_apps or new_pkgs or mode_escalated:
                    raise PermissionError(
                        f"Upgrade of {tool_id} to {version} expands privileges (hosts={sorted(new_hosts)}, apps={sorted(new_apps)}, pkgs={sorted(new_pkgs)}, mode_escalated={mode_escalated}). Explicit approval required."
                    )

        wf_path = self.install_dir / f"{tool_id}.workflow.json"
        wf.save(wf_path)
        record = {
            "tool_id": tool_id,
            "version": version,
            "publisher_id": pub_id,
            "public_key": pub_key,
            "workflow_sha256": manifest["workflow_sha256"],
            "workflow_path": str(wf_path),
            "target": wf.target,
            "mode": wf.mode,
        }
        installed[tool_id] = record
        self._save_installed(installed)
        return record

    def install_from_registry(
        self,
        tool_id: str,
        version: Optional[str] = None,
        allow_privilege_expansion: bool = False,
    ) -> Dict[str, Any]:
        if self.registry is None:
            raise RuntimeError("No ToolRegistry attached to MarketplaceManager.")
        zip_bytes, meta = self.registry.download_package_bytes(tool_id, version=version)
        return self.install_from_bytes(
            zip_bytes=zip_bytes,
            expected_publisher_key=meta["public_key"],
            allow_privilege_expansion=allow_privilege_expansion,
        )

    def list_installed(self) -> List[Dict[str, Any]]:
        return list(self._load_installed().values())

    def uninstall(self, tool_id: str) -> bool:
        installed = self._load_installed()
        if tool_id not in installed:
            return False
        wf_path = self.install_dir / f"{tool_id}.workflow.json"
        if wf_path.exists():
            wf_path.unlink()
        del installed[tool_id]
        self._save_installed(installed)
        return True
