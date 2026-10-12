"""Release-hardening regression tests. Device behavior is explicitly simulated."""
from __future__ import annotations
import copy
import hashlib
import json
import os
import threading
from pathlib import Path
from types import SimpleNamespace
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from unittest.mock import MagicMock

import pytest

from human2api.models import WorkflowError, save_workflow, validate_workflow
from human2api.editor import EditConflict, save_revision, revision, inspect_definition
from human2api.execution import target_lease
from human2api.vault import Vault
from human2api.registry import Registry, make_registry
from human2api.marketplace import pack_workflow
from human2api.trust import generate_keypair
from human2api.batch import read_rows, run_batch


def readflow():
    return {"schemaVersion":1,"name":"safe_read","description":"Read the approved app","target":"desktop","permissions":"read","steps":[{"action":"ui_extract_text","windowTitle":"Notes","automationId":"status","as":"result"}]}


def test_vault_encryption_unicode_and_wrong_password(tmp_path):
    path=tmp_path/'secrets.vault';password='long test passphrase'
    with Vault(path,password,create=True) as vault:
        vault.set('example','private-'+chr(0x0646)+chr(0x0648)+chr(0x0631))
        assert vault.names()==['example']
    assert b'private-' not in path.read_bytes() and b'example' not in path.read_bytes()
    with pytest.raises(WorkflowError,match='passphrase|modified'):
        Vault(path,'incorrect long password')
    with Vault(path,password) as vault:
        assert vault.get('example').startswith('private-')
        vault.delete('example');assert not vault.names()
    with pytest.raises(WorkflowError,match='locked'):
        vault.get('example')


def test_vault_rejects_tampering_stale_writes_and_symlinks(tmp_path):
    path=tmp_path/'vault';pw='a long passphrase!'
    a=Vault(path,pw,create=True);b=Vault(path,pw)
    a.set('first','value')
    with pytest.raises(WorkflowError,match='changed'):
        b.set('second','other')
    a.close();b.close()
    doc=json.loads(path.read_text());doc['nonce']='AAAAAAAAAAAAAAAA';path.write_text(json.dumps(doc))
    with pytest.raises(WorkflowError,match='modified'):
        Vault(path,pw)
    if os.name!='nt':
        alias=tmp_path/'alias';alias.symlink_to(path)
        with pytest.raises(WorkflowError,match='symlink'):Vault(alias,pw)


def test_vault_short_passphrase_rejected(tmp_path):
    with pytest.raises(WorkflowError,match='12'):
        Vault(tmp_path/'vault','short',create=True)
    assert not (tmp_path/'vault').exists()


def test_editor_cas_backups_and_validation(tmp_path):
    folder=tmp_path/'workflows';wf=readflow()
    rev=save_revision(folder,wf['name'],wf,'new')
    changed=copy.deepcopy(wf);changed['description']='Updated workflow'
    new=save_revision(folder,wf['name'],changed,rev)
    assert new!=rev
    with pytest.raises(EditConflict):save_revision(folder,wf['name'],wf,rev)
    assert (tmp_path/'.h2a/revisions/safe_read'/f'{rev}.json').is_file()
    report=inspect_definition(changed)
    assert not report['executed'] and report['warnings']


def test_editor_api_requires_revision_and_auth(local_server):
    server,folder,url=local_server;wf=readflow()
    headers={'X-H2A-Token':server.token,'Content-Type':'application/json'}
    raw=json.dumps(wf).encode()
    endpoint=url+'/api/editor/save/safe_read'
    with pytest.raises(HTTPError) as err:urlopen(Request(endpoint,data=raw,headers=headers))
    assert err.value.code==428
    with urlopen(Request(endpoint,data=raw,headers={**headers,'If-Match':'new'})) as response:
        value=json.load(response);assert value['saved']
    with pytest.raises(HTTPError) as err:urlopen(Request(endpoint,data=raw,headers={**headers,'If-Match':'new'}))
    assert err.value.code==409
    with urlopen(Request(url+'/api/editor/workflows/safe_read',headers=headers)) as response:
        assert json.load(response)['revision']==value['revision']
    with urlopen(url+'/editor') as response:
        assert server.token.encode() in response.read()
    with pytest.raises(HTTPError):urlopen(Request(url+'/api/editor/validate',data=raw,headers={'Content-Type':'application/json'}))


def test_native_lease_rejects_competing_session_and_releases_on_error():
    with target_lease('desktop'):
        with pytest.raises(WorkflowError,match='busy'):
            with target_lease('desktop'):pass
        with target_lease('browser'):pass
    with target_lease('desktop'):pass


def test_batch_validates_all_rows_before_execution(tmp_path,sample):
    path=tmp_path/'inputs.csv';path.write_text('customer_name,amount\nAlice,20.5\nBob,21\n')
    rows=read_rows(path,sample);assert rows[0]['amount']==20.5
    runner=MagicMock(return_value={'runId':'abc'})
    result=run_batch(sample,rows,approve=True,runner=runner)
    assert result['completed']==2 and 'Alice' not in json.dumps(result)
    runner.reset_mock()
    with pytest.raises(WorkflowError):run_batch(sample,[rows[0],{'customer_name':'bad'}],approve=True,runner=runner)
    runner.assert_not_called()


def test_batch_stops_after_failure_without_retries(sample):
    calls=[]
    def runner(*args,**kwargs):
        calls.append(1)
        if len(calls)==2:raise WorkflowError('sensitive error detail')
        return {'runId':'abc'}
    rows=[{'customer_name':'A','amount':1} for _ in range(4)]
    result=run_batch(sample,rows,approve=True,runner=runner)
    assert not result['ok'] and len(calls)==2 and 'sensitive' not in json.dumps(result)


def test_ambiguous_browser_selector_never_chooses_first():
    from human2api.runner import _locator
    page=MagicMock();page.locator.return_value.count.return_value=2
    with pytest.raises(WorkflowError,match='ambiguous'):_locator(page,{'selector':'button'},500)


def test_sensitive_artifacts_require_separate_permission(tmp_path,sample):
    from human2api.runner import run_workflow
    sample['inputs']['customer_name']['secret']=True
    with pytest.raises(WorkflowError,match='allowSensitiveArtifacts'):
        run_workflow(sample,{'customer_name':'PRIVATE','amount':1},approve_writes=True,artifacts_dir=tmp_path)
    assert not list(tmp_path.iterdir())


def test_metadata_healing_never_guesses_ambiguous_controls():
    from human2api.healing import recover_metadata
    items=[{'automationId':'new','name':'Save','controlType':'Button'}]
    assert recover_metadata({'name':'Save','controlType':'Button'},items)['automationId']=='new'
    assert recover_metadata({'name':'Save'},items*2) is None
    assert recover_metadata({'name':'Save'},[{**items[0],'isPassword':True}]) is None


def test_native_ax_uses_valuepattern_for_unicode_and_blocks_password():
    from human2api.native import AXControl
    api=MagicMock()
    values={'AXRole':'AXTextField','AXSubrole':'','AXTitle':'Comment','AXIdentifier':'note'}
    api.AXUIElementCopyAttributeValue.side_effect=lambda obj,key,out:(0,values.get(key))
    api.AXUIElementSetAttributeValue.return_value=0
    control=AXControl('test-object',api)
    text='hello '+chr(0x0645)
    control.set_edit_text(text)
    api.AXUIElementSetAttributeValue.assert_called_once_with('test-object','AXValue',text)
    values['AXSubrole']='AXSecureTextField'
    with pytest.raises(WorkflowError,match='password'):control.window_text()


def test_native_atspi_text_and_click_contract():
    from human2api.native import AtspiControl
    obj=MagicMock();obj.getAttributes.return_value=['id:save'];obj.getRoleName.return_value='push button';obj.name='Save'
    obj.queryAction.return_value.nActions=1;obj.queryAction.return_value.getName.return_value='click';obj.queryAction.return_value.doAction.return_value=True
    control=AtspiControl(obj,MagicMock());assert control.element_info.automation_id=='save'
    control.click_input();obj.queryAction.return_value.doAction.assert_called_once_with(0)
    obj.queryEditableText.return_value.setTextContents.return_value=False
    with pytest.raises(WorkflowError,match='rejected'):control.set_edit_text('text')


def test_packaged_examples_initialize_without_overwrites(tmp_path):
    from human2api.workspace import initialize
    assert len(initialize(tmp_path,port=9988))==3
    wf=json.loads((tmp_path/'create_invoice.json').read_text());assert ':9988/' in wf['startUrl']
    assert initialize(tmp_path)==[]


@pytest.fixture
def registry_fixture(tmp_path):
    store=Registry(tmp_path/'registry')
    private,public=tmp_path/'private.pem',tmp_path/'public.pem';generate_keypair(private,public)
    token=store.enroll('alice',public)
    source=save_workflow(tmp_path/'safe_read.json',readflow())
    package=pack_workflow(source,tmp_path/'safe_read.h2a.zip',publisher='alice',sign_key=private,release_version='1.0.0')
    return store,token,package,public


def test_registry_publish_search_signature_and_immutability(registry_fixture):
    store,token,package,public=registry_fixture
    result=store.publish(token,'1.0.0',package.read_bytes())
    assert result['sha256']==hashlib.sha256(package.read_bytes()).hexdigest()
    assert store.catalog('alice')[0]['reviewCount']==0
    assert store.download('alice','safe_read','1.0.0')==package.read_bytes()
    with pytest.raises(WorkflowError,match='immutable'):store.publish(token,'1.0.0',package.read_bytes())
    assert token.encode() not in store.db_path.read_bytes()
    store.yank(token,'safe_read','1.0.0');assert not store.catalog()
    with pytest.raises(WorkflowError):store.download('alice','safe_read','1.0.0')


def test_registry_rejects_impersonation_and_unsigned(registry_fixture,tmp_path):
    store,token,package,public=registry_fixture
    other_private,other_public=tmp_path/'other-private',tmp_path/'other-public';generate_keypair(other_private,other_public)
    source=tmp_path/'safe_read.json'
    impostor=pack_workflow(source,tmp_path/'impostor.h2a.zip',publisher='alice',sign_key=other_private)
    unsigned=pack_workflow(source,tmp_path/'unsigned.h2a.zip',publisher='alice')
    for path in (impostor,unsigned):
        with pytest.raises(WorkflowError):store.publish(token,'1.0.0',path.read_bytes())
    assert not store.catalog()
    with pytest.raises(WorkflowError):store.publish('invalid-token','1.0.0',package.read_bytes())


def test_registry_ratings_revocation_and_key_pinning(registry_fixture,tmp_path):
    store,token,package,public=registry_fixture
    store.publish(token,'1.0.0',package.read_bytes())
    with pytest.raises(WorkflowError,match='self-review'):store.rate(token,'alice','safe_read',5)
    key,pub=tmp_path/'bob-key',tmp_path/'bob-pub';generate_keypair(key,pub);bob=store.enroll('bob',pub)
    store.rate(bob,'alice','safe_read',4)
    assert store.catalog()[0]['stars']==4
    store.rate(bob,'alice','safe_read',3);assert store.catalog()[0]['reviewCount']==1
    store.revoke('bob');assert store.catalog()[0]['reviewCount']==0
    store.revoke('alice');assert not store.catalog()
    with pytest.raises(WorkflowError,match='revoked'):store.authenticate(token)


def test_registry_http_publish_and_install_upgrade(registry_fixture,tmp_path):
    import base64
    from human2api.registry_client import install
    store,token,package,public=registry_fixture
    server=make_registry(store.directory,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    origin=server.public_origin
    try:
        request=Request(origin+'/v1/publish',data=json.dumps({'version':'1.0.0','package':base64.b64encode(package.read_bytes()).decode()}).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
        with urlopen(request) as response:assert response.status==201
        installed=install(origin,'alice','safe_read','1.0.0',tmp_path/'installed',public,approve=True)
        assert installed.exists()
        with pytest.raises(WorkflowError):install(origin,'alice','safe_read','1.0.0',tmp_path/'installed',public,approve=True)
        upgraded=pack_workflow(tmp_path/'safe_read.json',tmp_path/'upgrade.h2a.zip',publisher='alice',sign_key=tmp_path/'private.pem',release_version='1.1.0')
        store.publish(token,'1.1.0',upgraded.read_bytes())
        assert install(origin,'alice','safe_read','1.1.0',tmp_path/'installed',public,approve=True,upgrade=True).exists()
        with pytest.raises(WorkflowError,match='newer'):install(origin,'alice','safe_read','1.0.0',tmp_path/'installed',public,approve=True,upgrade=True)
        with pytest.raises(HTTPError) as err:urlopen(Request(origin+'/v1/packages',headers={'Origin':'https://attacker.invalid'}))
        assert err.value.code==403
    finally:
        server.shutdown();server.server_close();thread.join()


def test_companion_only_accepts_loopback_token_and_scoped_unicode(monkeypatch):
    from human2api import companion
    with pytest.raises(WorkflowError,match='Arm'):companion.action('com.example.app','set_text',value='hello')
    monkeypatch.setenv('H2A_ANDROID_BRIDGE_TOKEN','a'*64)
    response=MagicMock();response.__enter__.return_value=response;response.read.return_value=b'{"ok":true}'
    opener=MagicMock();opener.open.return_value=response;monkeypatch.setattr(companion,'build_opener',lambda *args:opener)
    assert companion.action('com.example.app','set_text',selector='com.example:id/comment',value=chr(0x0645))['ok']
    request=opener.open.call_args.args[0]
    assert request.full_url=='http://127.0.0.1:8766/action' and json.loads(request.data)['package']=='com.example.app'
    monkeypatch.setenv('H2A_ANDROID_BRIDGE_PORT','8766/../../bad')
    with pytest.raises(WorkflowError,match='port'):companion.action('com.example.app','click')


def test_companion_native_sources_have_explicit_consent_and_no_text_recording():
    import re
    root=Path(__file__).resolve().parents[1]
    java=(root/'android-companion/app/src/main/java/dev/human2api/companion/CompanionService.java').read_text()
    recording=java.split('void onAccessibilityEvent',1)[1].split('public synchronized JSONObject workflow',1)[0]
    recording=re.sub(r'//[^\n]*','',recording)
    assert 'getText(' not in recording and 'isPassword()' in recording
    assert '127.0.0.1' in java and 'MessageDigest.isEqual' in java and 'armed' in java
    assert 'setText' not in recording and 'ACTION_SET_TEXT' in java


def test_registry_rejects_relabeling_an_old_signed_version(registry_fixture):
    store,token,package,public=registry_fixture
    with pytest.raises(WorkflowError,match='releaseVersion'):
        store.publish(token,'9.0.0',package.read_bytes())
    assert not store.catalog()


def test_android_rejects_cross_package_or_disabled_node():
    from human2api.android import resolve_node,AndroidSession
    from xml.etree.ElementTree import Element
    session=MagicMock();session.find_node.return_value=Element('node',{'package':'wrong.app'})
    with pytest.raises(WorkflowError,match='outside'):
        resolve_node(session,{'selector':'id'}, {}, package='approved.app')
    native=object.__new__(AndroidSession)
    with pytest.raises(WorkflowError,match='disabled'):
        native.tap_resolved(Element('node',{'enabled':'false','bounds':'[0,0][20,20]'}))
