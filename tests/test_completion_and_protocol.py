"""No device mocks are presented as real-device acceptance evidence."""
from __future__ import annotations
import copy
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from human2api import mcp_server as mcp
from human2api.models import WorkflowError, validate_workflow, save_workflow
from human2api.completion import junit_summary, repair_generated, ReleaseSession, source_digest

ROOT = Path(__file__).resolve().parents[1]


def modern(method='server/discover', id_=1, **params):
    return {'jsonrpc':'2.0','id':id_,'method':method,'params':{'_meta':{
        mcp.VERSION_KEY:mcp.MODERN,mcp.CAPABILITIES_KEY:{}},**params}}


def test_modern_discovery_and_legacy_fallback(tmp_path):
    response=mcp.handle_message(modern(),tmp_path)['result']
    assert mcp.MODERN in response['supportedVersions'] and response['resultType']=='complete'
    assert response['_meta']['io.modelcontextprotocol/serverInfo']['name']=='human2api'
    old=mcp.handle_message({'jsonrpc':'2.0','id':2,'method':'initialize','params':{'protocolVersion':'2024-11-05'}},tmp_path)
    assert old['result']['protocolVersion']=='2024-11-05' and 'resultType' not in old['result']


@pytest.mark.parametrize('bad', ['future-version', '', None])
def test_modern_protocol_version_rejected(tmp_path,bad):
    request=modern();request['params']['_meta'][mcp.VERSION_KEY]=bad
    response=mcp.handle_message(request,tmp_path)
    assert response['error']['code'] in {-32022,-32602}


def test_modern_requires_metadata_and_valid_client_info(tmp_path):
    request=modern();request['params']['_meta'].pop(mcp.CAPABILITIES_KEY)
    assert mcp.handle_message(request,tmp_path)['error']['code']==-32602
    request=modern();request['params']['_meta']['io.modelcontextprotocol/clientInfo']='bad'
    assert mcp.handle_message(request,tmp_path)['error']['code']==-32602
    assert mcp.handle_message(modern(id_=True),tmp_path)['error']['code']==-32600
    assert mcp.handle_message(modern(params=[]),tmp_path)['result']['resultType']=='complete'


def test_mcp_async_cancellation_suppresses_responses_and_allows_ping(monkeypatch,tmp_path):
    started=threading.Event();stopped=threading.Event();messages=[]
    def operation(*args,**kwargs):
        started.set()
        event=kwargs['cancel_event'];event.wait(3);stopped.set()
        return {'ok':True}
    monkeypatch.setattr(mcp,'_tool_call',operation)
    session=mcp.StdioSession(tmp_path,messages.append)
    session.feed(modern('tools/call',name='h2a_test'))
    assert started.wait(1)
    session.feed(modern('ping',id_=2))
    assert any(x.get('id')==2 for x in messages)
    session.feed({'jsonrpc':'2.0','method':'notifications/cancelled','params':{'requestId':1}})
    assert stopped.wait(1)
    session.close()
    assert not any(x.get('id')==1 for x in messages)


def test_mcp_progress_is_monotonic_and_only_requested(monkeypatch,tmp_path):
    messages=[]
    def operation(*args,**kwargs):
        fn=kwargs['on_step'];fn(1,'wait_ms','running');fn(1,'wait_ms','passed');fn(2,'wait_ms','passed')
        return {'ok':True}
    monkeypatch.setattr(mcp,'_tool_call',operation)
    session=mcp.StdioSession(tmp_path,messages.append)
    request=modern('tools/call',name='h2a_test');request['params']['_meta']['progressToken']='p'
    session.feed(request)
    deadline=time.monotonic()+2
    while session.running and time.monotonic()<deadline:time.sleep(.01)
    session.close()
    assert [x['params']['progress'] for x in messages if x.get('method')=='notifications/progress']==[1,2]
    assert messages[-1]['id']==1


def test_mcp_cursor_rejects_changed_catalog(monkeypatch,tmp_path):
    tools=[{'name':str(x)} for x in range(65)]
    monkeypatch.setattr(mcp,'mcp_tools',lambda _:tools)
    first=mcp.handle_message(modern('tools/list'),tmp_path)['result']
    assert len(first['tools'])==50
    second=mcp.handle_message(modern('tools/list',cursor=first['nextCursor']),tmp_path)['result']
    assert len(second['tools'])==15
    tools.append({'name':'new'})
    assert mcp.handle_message(modern('tools/list',cursor=first['nextCursor']),tmp_path)['error']['code']==-32602


def test_cross_process_device_lock_is_real_and_released(tmp_path,monkeypatch):
    from human2api.leases import device_lease
    monkeypatch.setenv('H2A_RUNTIME_DIR',str(tmp_path/'leases'))
    code="from human2api.leases import device_lease\nwith device_lease('desktop'): print('acquired')"
    with device_lease('desktop'):
        result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,timeout=10)
        assert result.returncode!=0 and 'busy' in result.stderr
    result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,timeout=10)
    assert result.returncode==0 and 'acquired' in result.stdout


def test_secret_redaction_keeps_long_nonsecret_output(monkeypatch,tmp_path):
    from human2api import runner
    wf={'schemaVersion':1,'name':'long_read','description':'Read','target':'desktop','permissions':'read','inputs':{'secret_value':{'type':'string','secret':True}},'steps':[{'action':'wait_ms','durationMs':100}]}
    text='x'*2400+'private-secret'
    monkeypatch.setattr(runner,'_run_workflow',lambda *a,**k:{'outputs':{'data':text}})
    result=runner.run_workflow(wf,{'secret_value':'private-secret'},artifacts_dir=tmp_path)
    assert result['outputs']['data']=='x'*2400+'[REDACTED]'


def test_junit_aggregate_counting_never_hides_skips(tmp_path):
    path=tmp_path/'report.xml'
    path.write_text('<testsuites tests="3"><testsuite><testcase/><testcase><skipped/></testcase><testcase><failure/></testcase></testsuite></testsuites>')
    assert junit_summary(path)=={'tests':3,'passed':1,'failures':1,'errors':0,'skipped':1}


def test_completion_local_scope_does_not_claim_release(tmp_path):
    s=ReleaseSession(ROOT,tmp_path/'reports')
    s.record('example','passed','simulated pipeline unit test')
    report=s.finish(scope='local')
    assert report['status']=='passed' and report['releaseReady'] is False
    assert json.loads((tmp_path/'reports/report.json').read_text())['releaseReady'] is False


def test_completion_missing_hardware_is_blocked(tmp_path):
    s=ReleaseSession(ROOT,tmp_path/'reports');s.acceptance(None)
    report=s.finish(scope='release')
    assert report['status']=='blocked' and not report['releaseReady']
    assert all(c['status']=='blocked' for c in report['checks'])


def test_completion_deterministic_repairs_are_idempotent(tmp_path):
    (tmp_path/'workflows').mkdir()
    assert len(repair_generated(tmp_path))==2
    assert repair_generated(tmp_path)==[]


def test_source_digest_ignores_generated_packaging(tmp_path):
    (tmp_path/'src/human2api').mkdir(parents=True);(tmp_path/'pyproject.toml').write_text('example')
    (tmp_path/'src/human2api/__init__.py').write_text('value=1')
    first=source_digest(tmp_path)
    (tmp_path/'src/example.egg-info').mkdir();(tmp_path/'src/example.egg-info/PKG-INFO').write_text('built')
    assert source_digest(tmp_path)==first
    (tmp_path/'src/human2api/__init__.py').write_text('value=2')
    assert source_digest(tmp_path)!=first


def test_closed_action_contract_rejects_missing_fields_and_extra_code():
    wf={'schemaVersion':1,'name':'bad','description':'Invalid','target':'desktop','steps':[{'action':'wait_ms'}]}
    with pytest.raises(WorkflowError):validate_workflow(wf)
    wf['steps']=[{'action':'wait_ms','durationMs':100,'python':'os.system(1)'}]
    with pytest.raises(WorkflowError):validate_workflow(wf)


def test_android_native_scroll_requires_package_and_selector():
    wf={'schemaVersion':1,'name':'android_scroll','description':'Scroll approved list','target':'android','steps':[{'action':'scroll_node','selector':'com.example:id/list','by':'resource-id','direction':'forward'}]}
    with pytest.raises(WorkflowError):validate_workflow(wf)
    wf['appPackage']='com.example.app';validate_workflow(wf)
    wf['steps'][0]['by']='text'
    with pytest.raises(WorkflowError):validate_workflow(wf)


def test_result_cache_purges_sensitive_outputs(local_server):
    server,_,_=local_server
    now=int(time.time())
    with server.lock:
        server.runs['old']={'state':'completed','finishedAt':now-3601,'outputs':{'private':'old'}}
        for index in range(110):server.runs[str(index)]={'state':'completed','finishedAt':now-index}
        server.runs['active']={'state':'running'}
        server.purge_results()
        assert 'old' not in server.runs and 'active' in server.runs and len(server.runs)==101


def test_registry_backup_restore_and_token_rotation(tmp_path):
    from human2api.registry import Registry
    from human2api.registry_backup import backup,restore
    from human2api.trust import generate_keypair
    private,public=tmp_path/'key',tmp_path/'pub';generate_keypair(private,public)
    store=Registry(tmp_path/'registry');old=store.enroll('alice',public)
    token=store.rotate_token('alice')
    assert store.authenticate(token)=='alice'
    with pytest.raises(WorkflowError):store.authenticate(old)
    out=tmp_path/'backup.sqlite3';checksum=backup(store,out)
    assert len(checksum)==64 and token.encode() not in out.read_bytes()
    restored=tmp_path/'restored';restore(out,restored)
    assert Registry(restored).authenticate(token)=='alice'
    with pytest.raises(WorkflowError):restore(out,restored)


def test_android_bridge_rotates_session_on_stop_and_hides_token_screen():
    java=ROOT/'android-companion/app/src/main/java/dev/human2api/companion'
    service=(java/'CompanionService.java').read_text()
    stop=service.split('void stopSession()',1)[1].split('private boolean active',1)[0]
    assert 'token=""' in stop and 'replies.clear()' in stop
    assert 'FLAG_SECURE' in (java/'MainActivity.java').read_text()


def test_completion_distinguishes_missing_tools_from_code_failure(tmp_path):
    session=ReleaseSession(ROOT,tmp_path/'result')
    cmd=[sys.executable,'-c','raise SystemExit(2)']
    assert session.command('missing-tool',cmd,blocked_codes=(2,))['status']=='blocked'
    assert session.command('bad-command',cmd)['status']=='failed'


def test_openapi_shared_editor_contract_resolves_internal_references(tmp_path,sample):
    from human2api.http_server import openapi_schema
    from jsonschema import Draft202012Validator,ValidationError
    spec=openapi_schema(tmp_path)
    schema={'$ref':'#/components/schemas/Workflow','components':spec['components']}
    validator=Draft202012Validator(schema)
    validator.validate(sample)
    bad=copy.deepcopy(sample);bad['steps'][0]['arbitraryPython']='unsafe'
    with pytest.raises(ValidationError):validator.validate(bad)
    for route in ('/api/editor/validate','/api/editor/save/{name}'):
        assert spec['paths'][route]['post']['requestBody']['content']['application/json']['schema']=={'$ref':'#/components/schemas/Workflow'}
