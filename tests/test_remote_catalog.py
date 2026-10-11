"""Remote workflow catalog: boundary conditions, integrity, explicit install consent."""
from __future__ import annotations

import hashlib
import json
from urllib.error import HTTPError
from unittest.mock import MagicMock

import pytest

from human2api import marketplace
from human2api.models import WorkflowError, save_workflow


class FakeResponse:
    def __init__(self, payload: bytes, **headers):
        self.payload = payload
        self.headers = headers

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, amount: int) -> bytes:
        return self.payload[:amount]


def index(package_url="https://example.com/workflow.h2a.zip", sha="a" * 64):
    return {"formatVersion": 1, "packages": [{
        "name": "create_invoice", "version": "0.2.0", "publisher": "test",
        "target": "browser", "description": "Test browser demo",
        "url": package_url, "sha256": sha,
    }]}


def mock_fetch(monkeypatch, payload: bytes, content_length: str | None = None):
    opener = MagicMock()
    hdr = {"Content-Length": content_length} if content_length is not None else {}
    opener.open.return_value = FakeResponse(payload, **hdr)
    monkeypatch.setattr("urllib.request.build_opener", lambda *handlers: opener)
    return opener


def test_catalog_accepts_verified_index(monkeypatch):
    opener = mock_fetch(monkeypatch, json.dumps(index()).encode())
    records = marketplace.remote_catalog("https://example.com/index.json")
    assert [x["name"] for x in records] == ["create_invoice"]
    opener.open.assert_called_once()
    assert opener.open.call_args[0][0].full_url == "https://example.com/index.json"


@pytest.mark.parametrize("url", [
    "http://example.com/index.json", "https://user:pass@example.com/index.json",
    "file:///etc/shadow", "https://example.com/index.json#fragment", "http://127.0.0.1/index.json",
])
def test_catalog_rejects_non_https_urls(url):
    with pytest.raises(WorkflowError, match="HTTPS"):
        marketplace.remote_catalog(url)


@pytest.mark.parametrize("change", [
    lambda d: d["packages"].append(d["packages"][0]),
    lambda d: d["packages"][0].update(sha256="invalid"),
    lambda d: d["packages"][0].update(name="../bad"),
    lambda d: d["packages"][0].update(target="shell"),
    lambda d: d["packages"][0].update(url="http://evil.com/workflow.zip"),
    lambda d: d["packages"][0].update(url=None),
    lambda d: d["packages"][0].update(url="https://evil.com/workflow.zip#bad"),
    lambda d: d["packages"][0].update(url="https://user:pass@evil.com/workflow.zip"),
    lambda d: d["packages"][0].update(unknown="anything"),
])
def test_catalog_rejects_invalid_entries(monkeypatch, change):
    data = index()
    change(data)
    mock_fetch(monkeypatch, json.dumps(data).encode())
    with pytest.raises(WorkflowError):
        marketplace.remote_catalog()


def test_catalog_rejects_large_payload_before_parse(monkeypatch):
    mock_fetch(monkeypatch, b"{}", str(marketplace.MAX_REGISTRY + 1))
    with pytest.raises(WorkflowError, match="too large"):
        marketplace.remote_catalog()


def test_remote_install_requires_consent_without_network(monkeypatch, tmp_path):
    monkeypatch.setattr(marketplace, "remote_catalog", lambda *_: pytest.fail("must not fetch index"))
    with pytest.raises(WorkflowError, match="--approve"):
        marketplace.install_remote("create_invoice", tmp_path, approve=False)


def test_remote_install_verified_round_trip_and_refuses_overwrite(monkeypatch, tmp_path, sample):
    source = save_workflow(tmp_path / "create_invoice.json", sample)
    package = marketplace.pack_workflow(source, tmp_path / "create_invoice.h2a.zip")
    package_data = package.read_bytes()
    entries = index(sha=hashlib.sha256(package_data).hexdigest())
    monkeypatch.setattr(marketplace, "remote_catalog", lambda *_: entries["packages"])
    opener = mock_fetch(monkeypatch, package_data)
    installed_dir = tmp_path / "installed"
    path = marketplace.install_remote("create_invoice", installed_dir, approve=True)
    assert path.is_file()
    assert json.loads(path.read_text())["name"] == "create_invoice"
    with pytest.raises(WorkflowError, match="already exists"):
        marketplace.install_remote("create_invoice", installed_dir, approve=True)
    assert opener.open.call_count == 2


def test_remote_install_rejects_mismatched_download(monkeypatch, tmp_path):
    monkeypatch.setattr(marketplace, "remote_catalog", lambda *_: index()["packages"])
    mock_fetch(monkeypatch, b"bad data")
    with pytest.raises(WorkflowError, match="checksum mismatch"):
        marketplace.install_remote("create_invoice", tmp_path, approve=True)


def test_remote_install_missing_catalog_entry(monkeypatch, tmp_path):
    monkeypatch.setattr(marketplace, "remote_catalog", lambda *_: [])
    with pytest.raises(WorkflowError, match="not found"):
        marketplace.install_remote("create_invoice", tmp_path, approve=True)


def test_catalog_does_not_follow_redirects(monkeypatch):
    def fail_redirect(*args):
        raise HTTPError("https://example.com/index.json", 302, "moved", {}, None)
    opener = MagicMock()
    opener.open.side_effect = fail_redirect
    monkeypatch.setattr("urllib.request.build_opener", lambda *args: opener)
    with pytest.raises(WorkflowError, match="could not be downloaded"):
        marketplace.remote_catalog()
