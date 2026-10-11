"""Release-gate tests for cancellation, desktop accessibility and signatures."""
import copy
import json
import os
import stat
import threading
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import pytest

from human2api import desktop, desktop_access, http_server
from human2api.execution import RunCancelled, check_cancelled, interruptible_wait, run_step_with_retry
from human2api.marketplace import inspect_package, install_package, pack_workflow
from human2api.models import WorkflowError, save_workflow, validate_workflow
from human2api.scheduler import LocalScheduler
from human2api.trust import generate_keypair


def _wf(name="test_flow", permission="write", steps=None, inputs=None):
    return {"schemaVersion": 1, "name": name, "description": "Example", "target": "desktop",
            "permissions": permission, "inputs": inputs or {}, "steps": steps or [{"action": "click", "x": 1, "y": 1}]}


def test_retries_only_read_operations():
    wf = _wf(steps=[{"action": "click", "x": 1, "y": 1, "retries": 3}])
    with pytest.raises(WorkflowError, match="read-only"):
        validate_workflow(wf)
    wf = _wf(permission="read", steps=[{"action":"ui_assert_text", "windowTitle":"Notes", "automationId":"text", "text":"Saved", "retries":2,"retryDelayMs":100}])
    assert validate_workflow(wf)
    wf["steps"][0]["retryDelayMs"] = 10
    with pytest.raises(WorkflowError, match="retryDelayMs"):
        validate_workflow(wf)


def test_accessibility_schema_requires_exact_window_and_identifier():
    for step in [
        {"action":"ui_click", "automationId":"ok"},
        {"action":"ui_click", "windowTitle":"Calculator"},
        {"action":"ui_fill", "windowTitle":"Calculator", "name":"Display"},
    ]:
        with pytest.raises(WorkflowError):
            validate_workflow(_wf(steps=[step]))
    assert validate_workflow(_wf(steps=[{"action":"ui_fill", "windowTitle":"Notes", "automationId":"edit", "value":"{{msg}}"}], inputs={"msg":{"type":"string"}}))


class FakeControl:
    def __init__(self, automation_id, name, control_type="Edit", visible=True, password=False, children=None):
        self.element_info = SimpleNamespace(automation_id=automation_id, name=name, control_type=control_type, is_password=password)
        self._visible = visible
        self._children = children or []
        self.text = "Saved item"
        self.clicked = False
        self.entered = None

    def is_visible(self): return self._visible
    def is_enabled(self): return True
    def descendants(self): return self._children
    def click_input(self): self.clicked = True
    def set_edit_text(self, text): self.entered = text
    def window_text(self): return self.text


def test_windows_accessibility_unicode_and_ambiguity(monkeypatch, tmp_path):
    visible = FakeControl("edit1", "Description")
    window = FakeControl("", "Notes", children=[visible, FakeControl("edit1", "Description", visible=False)])
    monkeypatch.setattr(desktop_access, "_desktop", lambda: SimpleNamespace(windows=lambda **kwargs: [window]))
    step = {"action":"ui_fill", "windowTitle":"Notes", "automationId":"edit1", "value":"{{text}}"}
    assert desktop_access.execute_ui_step(step, {"text":"أهلاً 🌍"}) is None
    assert visible.entered == "أهلاً 🌍"
    step = {"action":"ui_assert_text", "windowTitle":"Notes", "automationId":"edit1", "text":"Saved"}
    desktop_access.execute_ui_step(step, {})
    step["text"] = "Missing"
    with pytest.raises(WorkflowError): desktop_access.execute_ui_step(step, {})
    window._children.append(FakeControl("edit1", "Description"))
    with pytest.raises(WorkflowError, match="exactly one"):
        desktop_access.execute_ui_step(step, {})


def test_password_field_rejected(monkeypatch):
    window = FakeControl("", "Login", children=[FakeControl("passwd", "Password", password=True)])
    monkeypatch.setattr(desktop_access, "_desktop", lambda: SimpleNamespace(windows=lambda **kwargs: [window]))
    with pytest.raises(WorkflowError, match="password"):
        desktop_access.execute_ui_step({"action":"ui_click", "windowTitle":"Login", "automationId":"passwd"}, {})


def test_desktop_uia_can_run_without_mouse_library(monkeypatch, tmp_path):
    monkeypatch.setattr(desktop, "_gui", lambda: pytest.fail("should not require PyAutoGUI"))
    monkeypatch.setattr(desktop_access, "execute_ui_step", lambda step, vals: "Done")
    wf = _wf(permission="read", steps=[{"action":"ui_extract_text", "windowTitle":"Notes", "name":"body", "as":"result"}])
    from human2api.runner import run_workflow
    result = run_workflow(wf, approve_writes=False, artifacts_dir=tmp_path)
    assert result["outputs"]["result"] == "Done"


def test_cancel_event_interrupts_wait():
    stopped = threading.Event()
    stopper = threading.Timer(0.02, stopped.set)
    stopper.start()
    before = time.monotonic()
    with pytest.raises(RunCancelled): interruptible_wait(5000, stopped)
    assert time.monotonic() - before < 1
    stopper.join()


def test_retry_does_not_duplicate_writes():
    calls = []
    def transient():
        calls.append(1)
        if len(calls) < 3: raise WorkflowError("not yet")
        return "success"
    assert run_step_with_retry({"action":"assert_text", "retries":2, "retryDelayMs":100}, transient) == "success"
    assert len(calls) == 3
    wf = _wf(steps=[{"action":"click", "x": 1, "y": 1, "retries":1}])
    with pytest.raises(WorkflowError): validate_workflow(wf)


def test_package_signing_verification_and_tamper(tmp_path):
    key, pub = tmp_path/"key.pem",tmp_path/"pub.pem"
    generate_keypair(key, pub)
    if os.name != "nt": assert stat.S_IMODE(key.stat().st_mode) == 0o600
    with pytest.raises(WorkflowError, match="already exist"):
        generate_keypair(key, pub)
    source = save_workflow(tmp_path/"test_flow.json", _wf())
    pkg = pack_workflow(source, tmp_path/"signed.h2a.zip", sign_key=key, publisher="verified")
    manifest, workflow = inspect_package(pkg, trust_key=pub)
    assert manifest["packageVersion"] == 2 and "signature" in manifest
    assert workflow["name"] == "test_flow"
    assert install_package(pkg, tmp_path/"installed", trust_key=pub, approve=True).exists()
    other_priv, other_pub = tmp_path/"other.pem",tmp_path/"other-pub.pem"
    generate_keypair(other_priv, other_pub)
    with pytest.raises(WorkflowError, match="different publisher"):
        inspect_package(pkg, trust_key=other_pub)
    with zipfile.ZipFile(pkg) as z:
        man = json.loads(z.read("manifest.json"))
        flow = z.read("workflow.json")
    man["publisher"] = "attacker"
    bad = tmp_path/"bad.h2a.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("manifest.json", json.dumps(man))
        z.writestr("workflow.json", flow)
    with pytest.raises(WorkflowError, match="signature"):
        inspect_package(bad)


def test_unsigned_package_cannot_pass_pinned_trust(tmp_path):
    source=save_workflow(tmp_path/"test_flow.json",_wf())
    pkg=pack_workflow(source,tmp_path/"unsigned.h2a.zip")
    priv,pub=tmp_path/"pr.pem",tmp_path/"pub.pem"
    generate_keypair(priv,pub)
    with pytest.raises(WorkflowError,match="unsigned"):
        inspect_package(pkg,trust_key=pub)


def test_scheduler_keeps_secrets_out_of_registry(tmp_path):
    folder=tmp_path/"workflows";folder.mkdir()
    wf=_wf(inputs={"token":{"type":"string","secret":True}})
    save_workflow(folder/"test_flow.json",wf)
    store=LocalScheduler(folder)
    data_file=tmp_path/"inputs.json"
    data_file.write_text('{"token":"VERY-SECRET-STRING"}',encoding="utf-8")
    if os.name!="nt": data_file.chmod(0o600)
    with pytest.raises(WorkflowError,match="approve"):
        store.add("test_flow",every_minutes=5,data_file=data_file)
    schedule=store.add("test_flow",every_minutes=5,data_file=data_file,approve_writes=True)
    assert schedule["nextRunAt"] > schedule["createdAt"]
    assert "VERY-SECRET-STRING" not in store.registry.read_text()
    assert store.list()[0]["name"] == "test_flow"
    store.remove("test_flow")
    assert store.list()==[]


def test_scheduler_claims_jobs_and_writes_metadata(monkeypatch, tmp_path):
    folder=tmp_path/"workflows";folder.mkdir()
    save_workflow(folder/"safe.json",_wf(name="safe",permission="read",steps=[{"action":"wait_ms","durationMs":100}]))
    store=LocalScheduler(folder)
    job=store.add("safe",every_minutes=1)
    called=[]
    monkeypatch.setattr("human2api.scheduler.run_workflow", lambda *args,**kwargs: called.append(kwargs["run_id"]))
    events=store.run_due(now=job["nextRunAt"])
    assert len(events)==1 and events[0]["state"]=="completed"
    assert len(called)==1
    assert store.run_due(now=job["nextRunAt"])==[]
    assert store.list()[0]["lastState"]=="completed"


def test_http_cancel_real_local_server(local_server,monkeypatch):
    server,folder,url=local_server
    save_workflow(folder/"safe.json",_wf(name="safe",permission="read",steps=[{"action":"wait_ms","durationMs":4000}]))
    # Desktop requires a GUI even for waiting; fake it so we test actual HTTP and
    # cancellation in a background worker without touching the host mouse.
    monkeypatch.setattr(desktop,"_gui",lambda: Mock())
    def post(path,data):
        req=Request(url+path,method="POST",headers={"X-H2A-Token":server.token,"Content-Type":"application/json"},data=json.dumps(data).encode())
        with urlopen(req,timeout=3) as response:return response.status,json.load(response)
    _,accepted=post("/api/run/safe",{"inputs":{}})
    assert len(accepted["runId"])==24
    _,requested=post("/api/runs/"+accepted["runId"]+"/cancel",{})
    assert requested["state"]=="cancelling"
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        req=Request(url+"/api/runs/"+accepted["runId"],headers={"X-H2A-Token":server.token})
        with urlopen(req,timeout=3) as response:status=json.load(response)
        if status["state"]=="cancelled":break
        time.sleep(0.03)
    assert status["state"]=="cancelled"
    assert server.journal.get(accepted["runId"])["state"]=="cancelled"


def test_rest_scheduler_lifecycle(local_server):
    server, folder, url = local_server
    save_workflow(folder/"readjob.json", _wf(name="readjob", permission="read", steps=[{"action":"wait_ms","durationMs":100}]))
    def req(method,path,body=None,token=None):
        payload=None if body is None else json.dumps(body).encode()
        headers={"X-H2A-Token": token if token is not None else server.token}
        if payload is not None: headers["Content-Type"]="application/json"
        request=Request(url+path,method=method,headers=headers,data=payload)
        try:
            with urlopen(request,timeout=3) as res:return res.status,json.load(res)
        except HTTPError as exc: return exc.code,json.load(exc)
    assert req("GET","/api/schedules")[1]["schedules"]==[]
    assert req("POST","/api/schedules/add",{"name":"readjob","everyMinutes":2})[0]==201
    assert req("GET","/api/schedules")[1]["schedules"][0]["name"]=="readjob"
    assert req("POST","/api/schedules/add",{"name":"readjob","everyMinutes":2})[0]==400
    assert req("POST","/api/schedules/remove",{"name":"readjob"})[0]==200
    assert req("GET","/api/schedules")[1]["schedules"]==[]
    assert req("GET","/api/schedules",token="wrong")[0]==401


def test_record_desktop_smart_selector_at_point(monkeypatch):
    app = FakeControl("", "Untitled - Notes")
    ctrl = FakeControl("entry", "Text Box")
    ctrl.top_level_parent = lambda: app
    app.window_text = lambda: "Untitled - Notes"
    monkeypatch.setattr(desktop_access, "_desktop", lambda: SimpleNamespace(from_point=lambda x,y:ctrl))
    assert desktop_access.selector_at_point(10,20) == {"action":"ui_click","windowTitle":"Untitled - Notes","automationId":"entry","controlType":"Edit"}
    ctrl.element_info.is_password=True
    assert desktop_access.selector_at_point(10,20) is None
