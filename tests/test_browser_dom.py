"""Real DOM tests that can run even where managed Chromium blocks URLs."""
import json
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from human2api.recorder import RECORDER_SCRIPT, workflow_from_events
from human2api.runner import _run_step

STATIC = Path(__file__).resolve().parent.parent / 'src' / 'human2api' / 'static'


@pytest.mark.browser
def test_demo_ui_and_recording_on_blank_page(chromium_path, tmp_path):
    events = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=chromium_path)
        context = browser.new_context(accept_downloads=True)
        context.expose_binding('h2aBridge', lambda source, msg: events.append(msg))
        page = context.new_page()
        page.set_content((STATIC / 'demo.html').read_text())
        page.add_style_tag(content=(STATIC / 'demo.css').read_text())
        page.add_script_tag(content=(STATIC / 'demo.js').read_text())
        page.evaluate(RECORDER_SCRIPT)
        page.locator('#customer-name').fill('Secret customer')
        page.locator('#invoice-amount').fill('56.25')
        page.locator('#make-invoice').click()
        assert page.locator('#invoice-status').inner_text() == 'Invoice created successfully'
        assert 'Secret customer' in page.locator('#invoice-summary').inner_text()
        outputs={}
        _run_step(page, {'action':'download','selector':'#download-invoice','filename':'test-invoice.txt'}, {}, tmp_path, set(), outputs)
        assert '56.25' in (tmp_path / 'test-invoice.txt').read_text()
        assert len([e for e in events if e.get('action') == 'fill']) == 2
        assert 'Secret customer' not in json.dumps(events)
        wf=workflow_from_events('recorded_demo','Demo','https://localhost/demo',events)
        assert len(wf['inputs']) == 2
        assert len(wf['steps']) == 4
        assert not any('a:nth-of-type' in step.get('selector','') for step in wf['steps'])
        browser.close()


@pytest.mark.browser
def test_step_fallback_and_extract(chromium_path,tmp_path):
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True, executable_path=chromium_path)
        page=browser.new_page()
        page.set_content('<html><body><input id="customer-name" name="customer_name"><span id="result">ok</span></body></html>')
        _run_step(page,{'action':'fill','selector':'#old-name','alternatives':['#customer-name'],'value':'{{name}}','timeoutMs':700},{'name':'Real'},tmp_path,set(),{})
        assert page.locator('#customer-name').input_value()=='Real'
        outputs={}
        _run_step(page,{'action':'extract_text','selector':'#result','as':'value'}, {}, tmp_path,set(),outputs)
        assert outputs['value']=='ok'
        browser.close()


@pytest.mark.browser
def test_recorder_select_checkbox_no_form_values(chromium_path):
    events=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,executable_path=chromium_path)
        ctx=browser.new_context()
        ctx.expose_binding('h2aBridge',lambda source,msg:events.append(msg))
        page=ctx.new_page()
        page.set_content('<html><body><select name="category" id="category"><option value="a">A</option><option value="b">B</option></select><input type="checkbox" name="approved" id="approved"></body></html>')
        page.evaluate(RECORDER_SCRIPT)
        page.locator('#category').select_option('b')
        page.locator('#approved').check()
        page.wait_for_timeout(100)
        assert [e['action'] for e in events]==['select','check']
        assert all('value' not in e for e in events)
        wf=workflow_from_events('select_example','Select example','https://example.com',events)
        assert wf['steps'][0]['value']=='{{category}}'
        assert wf['steps'][1]['checked'] is True
        browser.close()
