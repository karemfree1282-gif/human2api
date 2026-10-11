"""Actual browser DOM tests; no remote network or localhost listener needed."""
from __future__ import annotations
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from playwright.sync_api import sync_playwright

from human2api.recorder import workflow_from_events, RECORDER_SCRIPT
from human2api.runner import _run_step, _locator
from human2api.models import validate_workflow, WorkflowError


@pytest.mark.browser
def test_multiframe_browser_step_and_semantic_healing(chromium_path, tmp_path):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=chromium_path) if chromium_path else playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content('<html><body><iframe id="child" srcdoc="<label for=\'user\'>Customer name</label><input id=\'user\'>"></iframe></body></html>')
        frame = page.frame_locator('iframe[id="child"]')
        frame.locator('input').wait_for()
        _run_step(page, {'action': 'fill', 'selector': '#user', 'frame': 'iframe[id="child"]', 'value': '{{customer}}'}, {'customer': 'Test'}, tmp_path, set(), {})
        assert frame.locator('input').input_value() == 'Test'
        outputs = {}
        _run_step(page, {'action': 'fill', 'selector': '#old-id', 'frame': 'iframe[id="child"]', 'value': '{{customer}}', 'label': 'Customer name', 'timeoutMs': 300}, {'customer': 'Recovered'}, tmp_path, set(), outputs, heal=True)
        assert frame.locator('input').input_value() == 'Recovered'
        assert outputs['healing'][0]['reviewRequired'] is True
        browser.close()


@pytest.mark.browser
def test_extended_browser_actions_and_tab_switch(chromium_path, tmp_path):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=chromium_path) if chromium_path else playwright.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        page.set_content('<input id="text"><button id="trigger">Go</button>')
        _run_step(page, {'action':'press','selector':'#text','key':'A'}, {}, tmp_path,set(),{})
        assert page.locator('#text').input_value() == 'A'
        _run_step(page, {'action':'hover','selector':'#trigger'}, {}, tmp_path,set(),{})
        _run_step(page, {'action':'scroll','selector':'#trigger','delta':1}, {}, tmp_path,set(),{})
        _run_step(page, {'action':'wait_ms','durationMs':100}, {}, tmp_path,set(),{})
        second = context.new_page(); second.set_content('<p id="target">hello</p>')
        assert context.pages[1].locator('#target').inner_text() == 'hello'
        browser.close()


def test_recorder_records_tabs_and_iframe_metadata_without_values():
    workflow = workflow_from_events('tabs_test','multi-tab','https://example.org/start?session=private',[
        {'action':'click','selector':'#open'},
        {'action':'switch_tab','index':1},
        {'action':'fill','selector':'#user','frame':'iframe[id="child"]','label':'Customer name','field':'customer','value':'do-not-save'},
        {'action':'switch_tab','index':0},
    ])
    validate_workflow(workflow)
    assert [a['action'] for a in workflow['steps']] == ['click','switch_tab','fill','switch_tab']
    assert workflow['steps'][2]['frame']=='iframe[id="child"]'
    assert 'do-not-save' not in json.dumps(workflow)
    assert 'private' not in json.dumps(workflow)


def test_frames_are_browser_only():
    data={'schemaVersion':1,'name':'wrong_frame','description':'No iframe on device','target':'android','permissions':'read','inputs':{},'steps':[{'action':'assert_text','text':'OK','frame':'iframe#x'}]}
    with pytest.raises(WorkflowError):validate_workflow(data)
