"""Keep JSON Schema aligned with portable workflow validation."""
import json
from pathlib import Path
from human2api.models import ACTIONS, TARGET_ACTIONS
p=Path(__file__).resolve().parents[1] / 'schemas/workflow.schema.json'
s=json.loads(p.read_text())
s['title']='Human2API Workflow v1 (browser / desktop / Android)'
s['description']='Portable, non-executable workflow definition compatible with Human2API 0.2'
s['required']=['schemaVersion','name','description','steps']
s['properties']['target']={'enum':['browser','desktop','android'],'default':'browser'}
s['properties']['deviceSerial']={'type':'string','pattern':'^[A-Za-z0-9._:-]{1,100}$'}
s['properties']['appPackage']={'type':'string','pattern':'^[A-Za-z][A-Za-z0-9_]*(\\.[A-Za-z0-9_]+)+$'}
item=s['properties']['steps']['items']
item['properties']['action']['enum']=sorted(ACTIONS)
item['properties'].update({
 'x':{'type':'integer','minimum':0,'maximum':16384},'y':{'type':'integer','minimum':0,'maximum':16384},
 'x2':{'type':'integer','minimum':0,'maximum':16384},'y2':{'type':'integer','minimum':0,'maximum':16384},
 'delta':{'type':'integer','minimum':-100,'maximum':100},
 'durationMs':{'type':'integer','minimum':100,'maximum':120000},
 'index':{'type':'integer','minimum':0,'maximum':20},
 'targetSelector':{'type':'string','minLength':1},
 'frame':{'type':'string','minLength':1,'maxLength':2048},
 'role':{'type':'string','minLength':1,'maxLength':150},
 'label':{'type':'string','minLength':1,'maxLength':150},
 'textHint':{'type':'string','minLength':1,'maxLength':150},
 'keys':{'type':'array','minItems':1,'maxItems':5,'items':{'type':'string','pattern':'^[a-z0-9_]{1,20}$'}},
 'key':{'type':'string','minLength':1,'maxLength':45},
 'by':{'enum':['text','resource-id','content-desc']},
 'image':{'type':'string','pattern':'^[^./\\\\][^/\\\\]*$','maxLength':128},
})
conditionals=item['allOf']
# Browser shared selector actions and Android selector actions differ, so scope
# the JSON schema required selector check using target-specific top-level logic
conditionals[0]={'if':{'properties':{'action':{'enum':sorted(set(TARGET_ACTIONS['browser']) - {'screenshot','navigate','wait_ms','switch_tab'} | {'tap_text','extract_text'})}},'required':['action']},'then':{'required':['selector']}}
conditionals.append({'if':{'properties':{'action':{'enum':['type_text','input_text']}},'required':['action']},'then':{'required':['value']}})
conditionals.append({'if':{'properties':{'action':{'enum':['click','double_click','move','tap','swipe']}},'required':['action']},'then':{'required':['x','y']}})
conditionals.append({'if':{'properties':{'action':{'const':'swipe'}},'required':['action']},'then':{'required':['x2','y2']}})
conditionals.append({'if':{'properties':{'action':{'const':'hotkey'}},'required':['action']},'then':{'required':['keys']}})
conditionals.append({'if':{'properties':{'action':{'enum':['press','keyevent']}},'required':['action']},'then':{'required':['key']}})
conditionals.append({'if':{'properties':{'action':{'const':'switch_tab'}},'required':['action']},'then':{'required':['index']}})
conditionals.append({'if':{'properties':{'action':{'const':'assert_image'}},'required':['action']},'then':{'required':['image']}})
conditionals.append({'if':{'properties':{'action':{'const':'wait_ms'}},'required':['action']},'then':{'required':['durationMs']}})
# Step action set depends on the workflow target.
def when_target(name):
    return {"if": {"properties": {"target": {"const": name}}, "required": ["target"]},
            "then": {"properties": {"steps": {"items": {"properties": {"action": {"enum": sorted(TARGET_ACTIONS[name])}}}}}}}
s["allOf"] = [
    {"if": {"not": {"required": ["target"]}}, "then": {"required": ["startUrl"]}},
    when_target("browser"), when_target("desktop"), when_target("android"),
    {"if": {"properties": {"target": {"const": "browser"}}, "required": ["target"]}, "then": {"required": ["startUrl"]}},
    {"if": {"properties": {"target": {"enum": ["desktop", "android"]}}, "required": ["target"]},
     "then": {"not": {"anyOf": [{"required": ["startUrl"]}, {"required": ["allowedHosts"]}]}}},
]
# Browser and desktop both use `click` but only browser uses `selector`; the
# Python validator performs this target-dependent check.
conditionals[0] = {"if": {"properties": {"action": {"enum": ["fill", "select", "check", "wait", "download", "hover", "press", "drag", "tap_text", "extract_text"]}}, "required": ["action"]}, "then": {"required": ["selector"]}}
conditionals = [x for x in conditionals if not (x.get("if", {}).get("properties", {}).get("action", {}).get("enum") == ["click", "double_click", "move", "tap", "swipe"])]
# Desktop coordinates and Android coordinates are required in Python validator;
# JSON schema keeps only cross-platform requirements here.
item["allOf"] = conditionals
p.write_text(json.dumps(s,indent=2,ensure_ascii=False)+'\n')
print('Saved portable schema')
