"""Generate static launch art and a truthful local-dashboard screenshot using test fixtures.

The dashboard screenshot is produced by rendering the real UI against the checked-in
sample workflow, with API responses mocked because it runs in a managed browser.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'docs' / 'assets'
ASSETS.mkdir(exist_ok=True, parents=True)


def font(size: int, bold=False):
    options = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf',
    ]
    for opt in options:
        if Path(opt).exists(): return ImageFont.truetype(opt, size)
    return ImageFont.load_default()


def og_card():
    img=Image.new('RGB',(1200,630),(8,16,27))
    pix=img.load()
    for y in range(630):
        for x in range(1200):
            dist=((x-850)/700)**2+((y-80)/500)**2
            glow=max(0.0,1-dist)
            pix[x,y]=(int(8+22*glow),int(16+59*glow),int(27+55*glow))
    d=ImageDraw.Draw(img)
    for r in [165,225,310,400]:
        d.ellipse((800-r,160-r,800+r,160+r),outline=(31,83,82),width=2)
    d.rounded_rectangle((56,57,118,119),radius=17,fill=(113,236,186))
    d.text((74,66),'h',font=font(44,True),fill=(7,26,34))
    d.text((139,66),'human2api',font=font(35,True),fill=(232,255,247))
    d.rounded_rectangle((66,193,410,228),radius=16,outline=(54,118,101),width=2,fill=(20,47,45))
    d.text((83,201),'OPEN SOURCE  /  LOCAL FIRST',font=font(15,True),fill=(135,241,190))
    d.text((66,258),'Teach it once.',font=font(77,True),fill=(241,252,255))
    d.text((66,348),'Automate forever.',font=font(70,True),fill=(122,244,194))
    d.text((69,462),'Turn browser workflows into MCP tools,',font=font(27),fill=(176,200,217))
    d.text((69,503),'CLI commands and local REST APIs.',font=font(27),fill=(176,200,217))
    d.line((67,582,1140,582),fill=(46,78,83),width=2)
    d.text((68,591),'github.com/karemfree1282-gif/human2api',font=font(18),fill=(137,179,185))
    img.save(ASSETS/'og-card.png',optimize=True)


def dashboard_screenshot():
    static=ROOT/'src'/'human2api'/'static'
    html=(static/'dashboard.html').read_text().replace('__H2A_LOCAL_TOKEN__','DEMO_ONLY_NO_REAL_TOKEN')
    css=(static/'app.css').read_text()
    js=(static/'app.js').read_text()
    wf=json.loads((ROOT/'workflows'/'create_invoice.json').read_text())
    entry={'name':wf['name'],'description':wf['description'],'permissions':wf['permissions'],'inputs':len(wf['inputs']),'steps':len(wf['steps'])}
    fake_fetch='''() => {window.fetch = async (url) => {
      if (url === '/api/workflows') return new Response(JSON.stringify({workflows: window.__fixture.entries}), {status:200,headers:{'Content-Type':'application/json'}});
      if (url.startsWith('/api/workflows/')) return new Response(JSON.stringify(window.__fixture.workflow), {status:200,headers:{'Content-Type':'application/json'}});
      return new Response(JSON.stringify({error:'Fixture only'}),{status:404,headers:{'Content-Type':'application/json'}});
    };}'''
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True, **({'executable_path':'/usr/bin/chromium'} if Path('/usr/bin/chromium').exists() else {}))
        try:
            page=browser.new_page(viewport={'width':1500,'height':1080}, device_scale_factor=1)
            page.set_content(html,wait_until='domcontentloaded')
            page.add_style_tag(content=css)
            page.evaluate('(value) => {window.__fixture=value;}',{'entries':[entry],'workflow':wf})
            page.evaluate(fake_fetch)
            page.add_script_tag(content=js)
            page.wait_for_function("document.getElementById('metric-workflows').textContent === '1'",timeout=5000)
            image_data=page.screenshot(full_page=True,animations='disabled')
            import io
            Image.open(io.BytesIO(image_data)).save(ASSETS/'dashboard-preview.webp','WEBP',quality=92,method=6)
        finally:
            browser.close()


if __name__=='__main__':
    og_card()
    dashboard_screenshot()
    print('Generated: docs/assets/og-card.png and docs/assets/dashboard-preview.webp')
