"""Shared action shape contracts for the runtime validator and generated schema."""
from __future__ import annotations
from typing import Any

SELECTOR = {"selector", "alternatives", "role", "label", "textHint", "frame", "frames"}
UI = {"windowTitle", "automationId", "name", "controlType"}
RETRY = {"wait", "assert_text", "extract_text", "assert_image", "ui_assert_text", "ui_extract_text"}


def action_contract(target: str, action: str) -> tuple[set[str], set[str]]:
    """Return (allowed, required) fields. This is not an execution permission."""
    common = {"action", "timeoutMs"}
    if action in RETRY:
        common |= {"retries", "retryDelayMs"}
    fields: set[str] = set()
    required = {"action"}
    if target == "browser":
        fields = set(SELECTOR) if action in {"click", "fill", "select", "check", "wait", "assert_text", "extract_text", "download", "press", "hover", "scroll", "drag"} else set()
        if fields:
            required.add("selector")
        data = {"fill":"value", "select":"value", "check":"checked", "assert_text":"text", "extract_text":"as", "navigate":"url", "press":"key", "drag":"targetSelector", "wait_ms":"durationMs", "switch_tab":"index"}
    elif target == "desktop":
        fields = set(UI) if action.startswith("ui_") else set()
        if fields:
            required.add("windowTitle")
        if action in {"click", "double_click", "move"}:
            fields |= {"x", "y"}; required |= {"x", "y"}
        data = {"type_text":"value", "ui_fill":"value", "ui_assert_text":"text", "ui_extract_text":"as", "hotkey":"keys", "press":"key", "wait_ms":"durationMs", "assert_image":"image", "scroll":"delta"}
    else:
        if action in {"tap", "swipe"}:
            fields |= {"x", "y"}; required |= {"x", "y"}
        if action == "swipe":
            fields |= {"x2", "y2", "durationMs"}; required |= {"x2", "y2"}
        if action in {"tap_text", "extract_text", "set_text", "scroll_node"}:
            fields |= {"selector", "by", "label", "role", "textHint"}; required.add("selector")
        data = {"set_text":"value", "input_text":"value", "keyevent":"key", "assert_text":"text", "extract_text":"as", "wait_ms":"durationMs", "scroll_node":"direction"}
    if action in data:
        fields.add(data[action]); required.add(data[action])
    if action in {"screenshot", "download"}:
        fields.add("filename")
    if action == "scroll":
        fields.add("delta")
    return common | fields, required


def workflow_schema() -> dict[str, Any]:
    from .models import NAME_RE, SERIAL_RE, PACKAGE_RE, TARGET_ACTIONS, WRITE_ACTIONS
    string = {"type":"string", "minLength":1, "maxLength":2048}
    filename = {"type":"string", "pattern":r"^[^./\\][^/\\]*$", "maxLength":128}
    properties: dict[str, Any] = {
        "selector":dict(string), "alternatives":{"type":"array", "maxItems":8, "items":{**string,"maxLength":2047}},
        "value":{"type":"string", "maxLength":10000}, "checked":{"type":["boolean","string"]},
        "text":dict(string), "as":{"type":"string","pattern":NAME_RE.pattern},
        "filename":filename, "image":filename, "url":dict(string), "targetSelector":dict(string),
        "frame":dict(string), "frames":{"type":"array","minItems":1,"maxItems":10,"items":dict(string)}, "keys":{"type":"array","minItems":1,"maxItems":5,"items":{"type":"string","pattern":"^[a-z0-9_]{1,20}$"}},
        "key":{**string,"maxLength":45}, "by":{"enum":["text","resource-id","content-desc"]},
        "direction":{"enum":["forward","backward"]},
        "timeoutMs":{"type":"integer","minimum":100,"maximum":120000},
        "durationMs":{"type":"integer","minimum":100,"maximum":120000},
        "retryDelayMs":{"type":"integer","minimum":100,"maximum":10000},
        "retries":{"type":"integer","minimum":0,"maximum":3},
        "index":{"type":"integer","minimum":0,"maximum":20},
        "delta":{"type":"integer","minimum":-100,"maximum":100},
    }
    for key in ("x","y","x2","y2"):
        properties[key]={"type":"integer","minimum":0,"maximum":16384}
    for key in ("role","label","textHint"):
        properties[key]={**string,"maxLength":150}
    for key in UI:
        properties[key]={**string,"maxLength":200}
    definitions={}
    for target, actions in TARGET_ACTIONS.items():
        variants=[]
        for action in sorted(actions):
            allowed, required=action_contract(target,action)
            fields={key:properties[key] for key in sorted(allowed-{"action"})}
            fields["action"]={"const":action}
            if target=="android" and "selector" in fields:
                fields["selector"]={**string,"maxLength":300}
            if action in {"set_text","scroll_node"}:
                fields["by"]={"enum":["resource-id","content-desc"]}
            item={"type":"object","additionalProperties":False,"properties":fields,"required":sorted(required)}
            if "frames" in fields:
                item["not"] = {"required":["frame","frames"]}
            if action.startswith("ui_"):
                item["anyOf"]=[{"required":["automationId"]},{"required":["name"]}]
            if action in RETRY:
                item["dependentRequired"]={"retryDelayMs":["retries"]}
            variants.append(item)
        definitions[target+"Step"]={"oneOf":variants}
    input_spec={"type":"object","additionalProperties":False,"properties":{
        "type":{"enum":["string","number","boolean"]},"required":{"type":"boolean"},"secret":{"type":"boolean"},
        "description":{"type":"string","maxLength":200},"default":{"type":["string","number","boolean"]}},
        "allOf":[{"if":{"properties":{"secret":{"const":True}},"required":["secret"]},"then":{"not":{"required":["default"]}}}]}
    root={"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"https://github.com/karemfree1282-gif/human2api/schemas/workflow.schema.json",
        "title":"Human2API portable workflow v1", "description":"Generated action shapes; the runtime additionally checks templates, hosts, filenames and values.",
        "type":"object","additionalProperties":False,"required":["schemaVersion","name","description","steps"],
        "properties":{"$schema":{"type":"string"},"schemaVersion":{"const":1},"name":{"type":"string","pattern":NAME_RE.pattern},
            "description":{**string,"maxLength":300},"target":{"enum":list(TARGET_ACTIONS)},
            "permissions":{"enum":["read","write"]},"startUrl":{**string,"pattern":"^https?://"},
            "allowedHosts":{"type":"array","minItems":1,"maxItems":30,"items":{"type":"string","minLength":1,"pattern":"^[a-z0-9.-]+$"}},
            "deviceSerial":{"type":"string","pattern":SERIAL_RE.pattern},"appPackage":{"type":"string","pattern":PACKAGE_RE.pattern},
            "networkPolicy":{"enum":["navigation","strict"]},"allowSensitiveArtifacts":{"type":"boolean"},
            "inputs":{"type":"object","maxProperties":80,"propertyNames":{"pattern":NAME_RE.pattern},"additionalProperties":input_spec},
            "steps":{"type":"array","minItems":1,"maxItems":250}},"$defs":definitions,"allOf":[]}
    for target in TARGET_ACTIONS:
        condition={"properties":{"target":{"const":target}},"required":["target"]}
        if target=="browser":
            condition={"anyOf":[condition,{"not":{"required":["target"]}}]}
        rule={"properties":{"steps":{"items":{"$ref":"#/$defs/"+target+"Step"}}}}
        if target=="browser":
            rule["required"]=["startUrl"]
            rule["not"]={"anyOf":[{"required":["deviceSerial"]},{"required":["appPackage"]}]}
        else:
            prohibited=["startUrl","allowedHosts","networkPolicy"]+(["deviceSerial","appPackage"] if target=="desktop" else [])
            rule["not"]={"anyOf":[{"required":[field]} for field in prohibited]}
        root["allOf"].append({"if":condition,"then":rule})
    root["allOf"].extend([
        {"if":{"properties":{"permissions":{"const":"read"}},"required":["permissions"]},"then":{"properties":{"steps":{"items":{"not":{"properties":{"action":{"enum":sorted(WRITE_ACTIONS)}},"required":["action"]}}}}}},
        {"if":{"properties":{"steps":{"contains":{"properties":{"action":{"enum":["set_text","scroll_node"]}},"required":["action"]}}}},"then":{"required":["appPackage"]}}
    ])
    return root
