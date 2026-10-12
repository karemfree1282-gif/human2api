"""Create a truthful GIF from the real DOM recorder and bundled fake invoice app.

Uses page.set_content so it also runs in browser environments where managed policy
blocks localhost. The final card uses the actual workflow_from_events output.
"""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

from human2api.recorder import RECORDER_SCRIPT, workflow_from_events

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'src' / 'human2api' / 'static'
OUT = ROOT / 'docs' / 'assets' / 'demo.gif'


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = 'DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'
    return ImageFont.truetype('/usr/share/fonts/truetype/dejavu/' + name, size)


def compose(screenshot: bytes, title: str, subtitle: str) -> Image.Image:
    bg=Image.new('RGB',(850,720),(10,17,29))
    draw=ImageDraw.Draw(bg)
    draw.text((35,20),'HUMAN2API  /  LIVE DEMO',font=font(16,True),fill=(130,244,189))
    draw.text((35,58),title,font=font(25,True),fill=(235,249,253))
    draw.text((35,99),subtitle,font=font(13),fill=(150,178,197))
    frame=Image.open(io.BytesIO(screenshot)).convert('RGB')
    frame.thumbnail((800,550))
    x=(850-frame.width)//2
    bg.paste(frame,(x,141))
    draw.rounded_rectangle((20,140,830,698),radius=14,outline=(47,83,88),width=2)
    return bg


def main():
    recorded=[]
    frames=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True, **({'executable_path':'/usr/bin/chromium'} if Path('/usr/bin/chromium').exists() else {}))
        try:
            ctx=browser.new_context(viewport={'width':750,'height':510},device_scale_factor=1)
            ctx.expose_binding('h2aBridge',lambda source,msg:recorded.append(msg))
            page=ctx.new_page()
            page.set_content((STATIC/'demo.html').read_text(encoding="utf-8"))
            page.add_style_tag(content=(STATIC/'demo.css').read_text(encoding="utf-8"))
            page.add_script_tag(content=(STATIC/'demo.js').read_text(encoding="utf-8"))
            page.evaluate(RECORDER_SCRIPT)
            frames.append(compose(page.screenshot(), '1. Start recording','The built-in fake invoice app is a safe test sandbox.'))
            page.locator('#customer-name').fill('Demo Customer')
            page.locator('#invoice-amount').click()
            frames.append(compose(page.screenshot(),'2. Teach the form','The recorder captures selectors, never the values typed.'))
            page.locator('#invoice-amount').fill('49.99')
            frames.append(compose(page.screenshot(),'3. Parameterize inputs','Human2API will create a variable for every filled field.'))
            page.locator('#make-invoice').click()
            frames.append(compose(page.screenshot(),'4. Verify the result','The fake invoice is created locally and visibly.'))
        finally:
            browser.close()
    wf=workflow_from_events('create_invoice_recorded','Invoice demonstration','http://127.0.0.1:8765/demo',recorded)
    final=Image.new('RGB',(850,720),(10,17,29))
    d=ImageDraw.Draw(final)
    d.text((35,20),'HUMAN2API  /  WORKFLOW GENERATED',font=font(16,True),fill=(130,244,189))
    d.text((35,64),'5. The automation is inspectable.',font=font(26,True),fill=(234,252,255))
    d.text((35,114),'These placeholders were generated from real events:',font=font(14),fill=(161,185,204))
    d.rounded_rectangle((32,166,819,573),radius=16,fill=(16,32,47),outline=(46,80,78),width=2)
    y=194
    for step in wf['steps']:
        lines=['{',f'  "action": "{step["action"]}",',f'  "selector": "{step["selector"]}"'+(',' if 'value' in step else '')]
        if 'value' in step:lines.append('  "value": "'+step['value']+'"')
        lines.append('}')
        if y + 15*len(lines) > 555:break
        for line in lines:
            d.text((58,y),line,font=font(15),fill=(136,247,194) if '{{' in line else (201,222,234))
            y+=21
        y+=10
    d.text((37,620),'Portable JSON  •  MCP + CLI + REST  •  Local-first',font=font(17,True),fill=(131,220,193))
    frames.append(final)
    palettes=[img.quantize(colors=64,method=Image.Quantize.FASTOCTREE) for img in frames]
    palettes[0].save(OUT,save_all=True,append_images=palettes[1:],duration=[1350,1300,1300,1800,3000],loop=0,optimize=True,disposal=2)
    print('Created',OUT,'size',OUT.stat().st_size)


if __name__=='__main__':
    main()
