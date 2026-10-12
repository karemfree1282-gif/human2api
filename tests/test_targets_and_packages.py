"""Capability and security tests that do not require a local GUI or device."""
from __future__ import annotations
import copy
import hashlib
import io
import json
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from human2api import android, desktop, healing
from human2api.marketplace import install_package, inspect_package, local_catalog, pack_workflow
from human2api.models import WorkflowError, save_workflow, validate_workflow, list_workflows
from human2api.runner import run_workflow


def desktop_flow(**kwargs):
    return {"schemaVersion": 1, "name": "my_desktop", "description": "Move and type into a GUI", "target": "desktop", "permissions": "write", "inputs": {"customer": {"type": "string", "required": True, "secret": True}}, "steps": [{"action": "click", "x": 10, "y": 11}, {"action": "type_text", "value": "{{customer}}"}, {"action": "hotkey", "keys": ["ctrl", "s"]}, {"action": "screenshot", "filename": "end.png"}], **kwargs}


def android_flow(**kwargs):
    return {"schemaVersion": 1, "name": "my_android", "description": "Tap a UI on Android", "target": "android", "deviceSerial": "emulator-5554", "permissions": "write", "inputs": {"who": {"type": "string", "required": True, "secret": True}}, "steps": [{"action": "tap", "x": 100, "y": 200}, {"action": "tap_text", "selector": "Save"}, {"action": "input_text", "value": "{{who}}"}, {"action": "assert_text", "text": "Saved"}, {"action": "screenshot"}], **kwargs}


def test_desktop_android_validate():
    assert validate_workflow(desktop_flow())["target"] == "desktop"
    assert validate_workflow(android_flow())["target"] == "android"


@pytest.mark.parametrize("step", [{"action": "tap", "x": -1, "y": 5}, {"action": "tap_text", "selector": "x", "by": "xpath"}, {"action": "shell", "value": "id"}, {"action": "swipe", "x": 1, "y": 1, "x2": -10, "y2": 5}])
def test_android_rejects_unsafe_steps(step):
    data = android_flow(); data["steps"] = [step]
    with pytest.raises(WorkflowError): validate_workflow(data)


@pytest.mark.parametrize("step", [{"action": "click", "x": True, "y": 2}, {"action": "type_text", "value": "abc", "command": "rm -rf"}, {"action": "hotkey", "keys": ["ctrl", "not+valid"]}, {"action": "screenshot", "filename": "../private.png"}])
def test_desktop_rejects_unsafe_steps(step):
    data = desktop_flow(); data["steps"] = [step]
    with pytest.raises(WorkflowError): validate_workflow(data)


def test_read_only_rejects_desktop_and_android_writes():
    for data in [desktop_flow(), android_flow()]:
        data["permissions"] = "read"
        with pytest.raises(WorkflowError, match="read-only"): validate_workflow(data)


def test_unknown_top_fields_rejected_and_legacy_remains_valid(sample):
    assert validate_workflow(sample)
    sample["python"] = "import os"
    with pytest.raises(WorkflowError, match="unknown workflow fields"): validate_workflow(sample)


def test_rejects_android_serial_and_package_injection():
    data = android_flow(); data["deviceSerial"] = "phone;rm -rf"
    with pytest.raises(WorkflowError): validate_workflow(data)
    data = android_flow(); data["appPackage"] = "$(echo hello)"
    with pytest.raises(WorkflowError): validate_workflow(data)


def test_output_lists_targets(tmp_path):
    save_workflow(tmp_path / "my_desktop.json", desktop_flow())
    save_workflow(tmp_path / "my_android.json", android_flow())
    assert {x["target"] for x in list_workflows(tmp_path)} == {"desktop", "android"}


class FakeScreenshot:
    def save(self, path):
        Path(path).write_bytes(b"test screenshot")


def test_desktop_runner_with_mock_gui(tmp_path, monkeypatch):
    gui = MagicMock()
    gui.screenshot.return_value = FakeScreenshot()
    monkeypatch.setattr(desktop, "_gui", lambda: gui)
    data = desktop_flow(allowSensitiveArtifacts=True)
    with pytest.raises(WorkflowError, match="approve"):
        run_workflow(data, {"customer": "Adam"}, artifacts_dir=tmp_path)
    result = run_workflow(data, {"customer": "Adam"}, approve_writes=True, artifacts_dir=tmp_path)
    gui.click.assert_called_once_with(10, 11)
    gui.write.assert_called_once_with("Adam", interval=0.02)
    gui.hotkey.assert_called_once_with("ctrl", "s")
    assert result["target"] == "desktop" and len(result["outputs"]["artifacts"]) == 1
    assert Path(result["outputs"]["artifacts"][0]).read_bytes() == b"test screenshot"
    assert "Adam" not in json.dumps(result)


def test_desktop_rejects_unapproved_shortcut_and_unicode(tmp_path, monkeypatch):
    gui = MagicMock()
    monkeypatch.setattr(desktop, "_gui", lambda: gui)
    wf = desktop_flow(); wf["steps"] = [{"action": "hotkey", "keys": ["ctrl", "r"]}]
    with pytest.raises(WorkflowError, match="not allowlisted|unsupported"):
        run_workflow(wf, {"customer": "Adam"}, approve_writes=True, artifacts_dir=tmp_path)
    wf["steps"] = [{"action": "type_text", "value": "{{customer}}"}]
    with pytest.raises(WorkflowError, match="ASCII"):
        run_workflow(wf, {"customer": "مرحبا"}, approve_writes=True, artifacts_dir=tmp_path)


@pytest.mark.parametrize("value,expected", [("Hello World", "Hello%sWorld"), ("A-9_test@email.com", "A-9_test@email.com")])
def test_safe_android_text(value, expected):
    assert android.encode_adb_text(value) == expected


@pytest.mark.parametrize("value", ["$(rm -rf /)", "Hi!", "مرحبا", "Hello\nWorld", "", "a"*1001])
def test_android_text_rejects_unsupported_values(value):
    with pytest.raises(WorkflowError): android.encode_adb_text(value)


def test_android_session_discovery_and_commands(monkeypatch):
    monkeypatch.setattr(android.shutil, "which", lambda value: "/usr/bin/adb")
    calls = []
    xml = b'<hierarchy><node text="Save" resource-id="com.example:id/save" content-desc="submit" bounds="[10,20][110,60]" /><node text="Saved" bounds="[20,80][110,110]" /></hierarchy>'
    def fake_run(args, **kwargs):
        calls.append(args)
        if args == ["adb", "devices"]:
            return SimpleNamespace(stdout="List of devices attached\nemulator-5554\tdevice\nother\tunauthorized\n")
        if args[-3:-1] == ["exec-out", "cat"] and args[-1].startswith("/data/local/tmp/human2api-"):
            return SimpleNamespace(stdout=xml)
        if args[-3:] == ["exec-out", "screencap", "-p"]:
            return SimpleNamespace(stdout=b"\x89PNG\r\n")
        return SimpleNamespace(stdout=b"")
    monkeypatch.setattr(android.subprocess, "run", fake_run)
    session = android.AndroidSession()
    assert session.serial == "emulator-5554"
    session.tap_node("Save")
    assert calls[-1][-5:] == ["shell", "input", "tap", "60", "40"]
    monkeypatch.setattr(android, "AndroidSession", lambda s=None: session)
    outputs = android.execute_android(android_flow(), {"who": "Alex"}, Path('/tmp'), None)
    assert outputs["artifacts"] and calls[-1][-3:] == ["exec-out", "screencap", "-p"]
    assert [x for x in calls if "input" in x and "text" in x]


def test_android_ambiguous_device_rejected(monkeypatch):
    monkeypatch.setattr(android, "adb_devices", lambda executable="adb": ["device-one", "device-two"])
    with pytest.raises(WorkflowError, match="exactly one"): android.AndroidSession()
    with pytest.raises(WorkflowError, match="not connected"): android.AndroidSession("unknown")


def test_package_roundtrip_and_refuse_overwrite(tmp_path):
    source = save_workflow(tmp_path / "my_desktop.json", desktop_flow())
    dest = tmp_path / "my_desktop.h2a.zip"
    pack_workflow(source, dest, publisher="test contributor")
    info, data = inspect_package(dest)
    assert info["publisher"] == "test contributor" and data["target"] == "desktop"
    assert local_catalog(tmp_path)[0]["name"] == "my_desktop"
    with pytest.raises(WorkflowError, match="--approve"):
        install_package(dest, tmp_path / "installed")
    installed = install_package(dest, tmp_path / "installed", approve=True)
    assert installed.read_text().find('"target": "desktop"') > 0
    with pytest.raises(WorkflowError, match="already exists"):
        install_package(dest, tmp_path / "installed", approve=True)


def test_package_rejects_zip_slip_and_invalid_hash(tmp_path):
    path = tmp_path / "evil.h2a.zip"
    with zipfile.ZipFile(path,"w") as z:
        z.writestr("../../etc/passwd", b"bad")
        z.writestr("manifest.json", b"{}")
    with pytest.raises(WorkflowError, match="only manifest"):
        inspect_package(path)
    source = save_workflow(tmp_path / "my_desktop.json", desktop_flow())
    good = tmp_path / "safe.h2a.zip"; pack_workflow(source, good)
    with zipfile.ZipFile(good) as z:
        manifest = json.loads(z.read("manifest.json"))
        workflow = z.read("workflow.json")
    manifest["workflowSha256"] = "0"*64
    bad = tmp_path / "bad.h2a.zip"
    with zipfile.ZipFile(bad,"w") as z:
        z.writestr("manifest.json", json.dumps(manifest))
        z.writestr("workflow.json", workflow)
    with pytest.raises(WorkflowError, match="checksum mismatch"):
        inspect_package(bad)


def test_healing_semantic_unique_and_ai_default_off(monkeypatch):
    element = MagicMock()
    element.count.return_value = 1
    element.first.is_visible.return_value = True
    page = MagicMock()
    page.get_by_label.return_value = element
    result = healing.recover(page, {"action": "fill", "label": "Customer name", "selector": "#old"})
    assert result[1] == "semantic"
    page.get_by_label.assert_called_once_with("Customer name", exact=True)


def test_healing_rejects_insecure_external_endpoint(monkeypatch):
    monkeypatch.setenv("H2A_AI_ENDPOINT", "http://api.example.com/chat/completions")
    with pytest.raises(WorkflowError, match="HTTPS"):
        healing._ai_endpoint()


def test_runner_rejects_ai_without_consent_and_sensitive_artifacts(tmp_path):
    with pytest.raises(WorkflowError, match="explicit"):
        run_workflow(desktop_flow(), {"customer": "a"}, approve_writes=True, artifacts_dir=tmp_path, ai_heal=True)
    with pytest.raises(WorkflowError, match="allowSensitiveArtifacts"):
        run_workflow(desktop_flow(), {"customer": "a"}, approve_writes=True, artifacts_dir=tmp_path, ai_heal=True, heal_selectors=True)


def test_package_rejects_executable_injection(tmp_path):
    path = tmp_path / 'malicious.h2a.zip'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('manifest.json', b'{}')
        z.writestr('workflow.json', b'{}')
        z.writestr('run.sh', b'echo unsafe')
    with pytest.raises(WorkflowError, match='only manifest'):
        inspect_package(path)


def test_gui_recorder_not_a_keylogger():
    from human2api.desktop import record_desktop
    import inspect
    source = inspect.getsource(record_desktop)
    assert 'on_release' not in source
    assert 'on_press' in source
    assert 'on_click' in source
    # Only the F12 termination key is processed; other keystrokes are never logged.
    assert 'keyboard.Key.f12' in source


def test_restrict_ai_redirect_and_bad_model_selector(monkeypatch):
    monkeypatch.setenv('H2A_AI_ENDPOINT','http://127.0.0.1:9999/v1/chat/completions')
    page = MagicMock()
    page.locator.return_value.evaluate_all.return_value = [{'tag':'button','id':'safe'}]
    fake = MagicMock()
    fake.status = 200
    fake.headers = {'Content-Length':'20'}
    fake.read.return_value = json.dumps({'choices':[{'message':{'content':'{"selector":"#unmatched"}'}}]}).encode()
    fake.__enter__.return_value = fake
    opener = MagicMock()
    opener.open.return_value = fake
    monkeypatch.setattr(healing, 'build_opener', lambda *a, **kw: opener)
    page.locator.return_value.count.return_value = 0
    assert healing.ai_selector(page, {'action':'click','selector':'#old'}) is None
    assert opener.open.call_count == 1
