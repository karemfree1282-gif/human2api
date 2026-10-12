"""Real Chromium DOM/UI behavior with explicit in-memory HTTP doubles.

These tests do not replace the URL end-to-end suite or physical device tests.
"""
import json
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright
from human2api.models import TARGET_ACTIONS, validate_workflow

STATIC = Path(__file__).resolve().parents[1]/'src/human2api/static'


@pytest.mark.browser
def test_visual_editor_all_actions_save_and_conflict(chromium_path,tmp_path):
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,executable_path=chromium_path)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('dialog',lambda dialog:dialog.accept())
        page.set_content((STATIC/'editor.html').read_text())
        page.add_style_tag(content=(STATIC/'editor.css').read_text())
        page.evaluate('''() => { window.requests=[];window.conflict=false;window.fetch=async (path,opts={})=>{
            window.requests.push({path,opts});let result={workflows:[]},status=200;
            if(path.includes('/validate'))result={valid:true,stepCount:JSON.parse(opts.body).steps.length,warnings:[]};
            if(path.includes('/save/')){result=window.conflict?{error:'workflow changed'}:{saved:true,revision:'abcdef0123456789'};status=window.conflict?409:200;}
            return new Response(JSON.stringify(result),{status,headers:{'Content-Type':'application/json'}});
        }}''')
        page.add_script_tag(content=(STATIC/'editor.js').read_text())
        for target in ('browser','desktop','android'):
            page.locator('#target').select_option(target)
            palette={x.removeprefix('+ ') for x in page.locator('#palette button').all_text_contents()}
            assert palette==TARGET_ACTIONS[target]
        page.locator('#target').select_option('browser')
        page.locator('#name').fill('ui_recording')
        page.locator('#palette button').get_by_text('+ fill',exact=True).click()
        page.locator('#palette button').get_by_text('+ assert_text',exact=True).click()
        assert page.locator('#step-count').inner_text()=='2'
        page.get_by_role('button',name='Up step 2',exact=True).click()
        assert page.locator('#steps .step-info strong').first.inner_text()=='assert_text'
        page.locator('#save').click()
        page.wait_for_function("document.getElementById('issues').textContent.includes('Saved.')")
        request=page.evaluate("requests.filter(r=>r.path.includes('/save/')).at(-1)")
        validate_workflow(json.loads(request['opts']['body']))
        assert request['opts']['headers']['If-Match']=='new'
        page.evaluate('conflict=true')
        page.locator('#save').click()
        page.wait_for_function("document.getElementById('issues').textContent.includes('workflow changed')")
        page.screenshot(path=str(tmp_path/'editor.png'),full_page=True)
        assert not errors
        browser.close()


@pytest.mark.browser
def test_registry_ui_renders_untrusted_labels_as_text(chromium_path,tmp_path):
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,executable_path=chromium_path)
        page=browser.new_page(viewport={'width':1320,'height':850})
        page.set_content((STATIC/'registry.html').read_text())
        page.add_style_tag(content=(STATIC/'editor.css').read_text())
        page.evaluate('''()=>{window.fetch=async()=>new Response(JSON.stringify({packages:[{
          publisher:'alice',name:'sample',version:'1.0.0',target:'browser',reviewCount:0,stars:null,
          description:'<img id="untrusted" src="x" onerror="alert(1)">',sha256:'a'.repeat(64)
        }]}),{headers:{'Content-Type':'application/json'}})}''')
        page.add_script_tag(content=(STATIC/'registry.js').read_text())
        page.wait_for_selector('#packages article')
        assert page.locator('#untrusted').count()==0
        assert '<img' in page.locator('#packages').inner_text()
        assert page.locator('#packages a').get_attribute('href')=='/v1/packages/alice/sample/1.0.0'
        page.screenshot(path=str(tmp_path/'registry.png'),full_page=True)
        browser.close()


@pytest.mark.browser
def test_nested_frame_actions_and_recorder_unique_selectors(chromium_path,tmp_path):
    from human2api.runner import _run_step
    from human2api.recorder import RECORDER_SCRIPT,workflow_from_events
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,executable_path=chromium_path)
        page=browser.new_page();page.set_content('<iframe id="outer"></iframe>')
        page.frames[1].set_content('<iframe id="inner"></iframe>')
        page.frames[-1].set_content('<input id="value"><span id="result">Verified</span>')
        step={'action':'fill','frames':['iframe#outer','iframe#inner'],'selector':'#value','value':'{{text}}'}
        _run_step(page,step,{'text':'nested'},tmp_path,set(),{})
        assert page.frame_locator('#outer').frame_locator('#inner').locator('#value').input_value()=='nested'
        events=[];ctx=browser.new_context();ctx.expose_binding('h2aBridge',lambda source,msg:events.append(msg));p=ctx.new_page()
        p.set_content('<input name="shared"><input name="shared">');p.evaluate(RECORDER_SCRIPT)
        p.locator('input').first.fill('private');p.locator('input').last.click();p.wait_for_timeout(50)
        first=next(e for e in events if e['action']=='fill')
        assert p.locator(first['selector']).count()==1
        duplicated=[first,{'action':'switch_tab','index':1},first]
        wf=workflow_from_events('separate_tabs','Test','https://example.org',duplicated)
        assert len(wf['inputs'])==2
        browser.close()
