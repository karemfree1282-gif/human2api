import json
from pathlib import Path
from urllib.request import urlopen

import pytest
from playwright.sync_api import sync_playwright

from human2api.models import WorkflowError
from human2api.recorder import RECORDER_SCRIPT, workflow_from_events
from human2api.runner import run_workflow


@pytest.fixture(autouse=True)
def require_browser_network(local_server, chromium_path):
    _, _, url = local_server
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=chromium_path)
        try:
            page = browser.new_page()
            try:
                page.goto(url + "/demo", timeout=3000)
            except Exception as exc:
                if "ERR_BLOCKED_BY_ADMINISTRATOR" in str(exc):
                    pytest.skip("local Chromium managed policy blocks all URLs; full end-to-end tests run in GitHub Actions")
                raise
        finally:
            browser.close()


@pytest.mark.browser
def test_real_invoice_browser_run(demo_flow, chromium_path, tmp_path):
    sample,_,_,url=demo_flow
    result=run_workflow(sample, {"customer_name":"Nadia Test","amount":49.99},approve_writes=True,artifacts_dir=tmp_path,browser_path=chromium_path)
    assert result["ok"] is True
    assert "Nadia Test" in result["outputs"]["confirmation"]
    invoice=Path(result["outputs"]["artifacts"][0])
    assert invoice.exists() and "49.99" in invoice.read_text()


@pytest.mark.browser
def test_browser_capture_privacy(demo_flow, chromium_path):
    _,_,_,url=demo_flow
    events=[]
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(headless=True, executable_path=chromium_path)
        context=browser.new_context()
        context.expose_binding('h2aBridge',lambda source,msg:events.append(msg))
        context.add_init_script(script=RECORDER_SCRIPT)
        page=context.new_page()
        page.goto(url+'/demo')
        page.locator('#customer-name').fill('Sensitive Name')
        page.locator('#invoice-amount').fill('599')
        page.locator('#make-invoice').click()
        page.wait_for_timeout(100)
        browser.close()
    assert any(e.get('action')=='click' for e in events)
    assert len([e for e in events if e.get('action')=='fill'])==2
    assert 'Sensitive Name' not in json.dumps(events)
    flow=workflow_from_events('replay_recorded','Test recording',url+'/demo',events)
    assert flow['steps'][0]['selector']=='#customer-name'
    assert flow['steps'][1]['selector']=='#invoice-amount'
    assert flow['steps'][2]['selector']=='#make-invoice'


@pytest.mark.browser
def test_browser_rejects_cross_origin_navigation(demo_flow,chromium_path,tmp_path):
    sample,_,_,url=demo_flow
    sample['steps']=[{'action':'navigate','url':'https://example.org'}]
    with pytest.raises(WorkflowError, match='outside allowedHosts'):
        run_workflow(sample,{'customer_name':'A','amount':1},approve_writes=True,browser_path=chromium_path,artifacts_dir=tmp_path)


@pytest.mark.browser
def test_resilient_fallback_selectors(demo_flow,chromium_path,tmp_path):
    sample,_,_,url=demo_flow
    sample['steps'][0]['selector']='#stale-removed-id'
    sample['steps'][0]['timeoutMs']=650
    result=run_workflow(sample,{'customer_name':'A','amount':1},approve_writes=True,browser_path=chromium_path,artifacts_dir=tmp_path)
    assert result['ok']
