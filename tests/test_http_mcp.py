import json
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from human2api.http_server import openapi_schema
from human2api.mcp_server import handle_message, mcp_tools
from human2api.models import save_workflow


def request_json(url, token="", method="GET", payload=None, origin=None, host=None):
    headers={"X-H2A-Token":token}
    if payload is not None: headers["Content-Type"]="application/json"
    if origin:headers["Origin"]=origin
    if host:headers["Host"]=host
    req=Request(url,headers=headers,method=method,data=json.dumps(payload).encode() if payload is not None else None)
    try:
        with urlopen(req,timeout=5) as res:
            return res.status,json.load(res)
    except HTTPError as exc:
        return exc.code,json.load(exc)


def test_rest_auth_and_host(demo_flow):
    _, server, folder, url=demo_flow
    code,body=request_json(url+"/health")
    assert code==200 and body["status"]=="ok"
    code,body=request_json(url+"/api/workflows")
    assert code==401
    code,body=request_json(url+"/api/workflows",server.token)
    assert code==200 and body["workflows"][0]["name"]=="create_invoice"
    code,body=request_json(url+"/api/workflows",server.token,origin="https://attacker.example")
    assert code==403
    code,body=request_json(url+"/api/workflows",server.token,host="rebind.example")
    assert code==403


def test_rest_record_blocked_without_approval(demo_flow):
    _,server,_,url=demo_flow
    code,body=request_json(url+"/api/run/create_invoice",server.token,method="POST",payload={"inputs": {"customer_name":"X","amount":1}})
    assert code==400 and "approve" in body["error"]


def test_rest_editor_validates_names(demo_flow):
    sample,server,_,url=demo_flow
    updated={**sample,"name":"wrong_name"}
    code,body=request_json(url+"/api/save/create_invoice",server.token,"POST",updated)
    assert code==400


def test_mcp_protocol(demo_flow):
    _,_,folder,_=demo_flow
    init=handle_message({"jsonrpc":"2.0","id":4,"method":"initialize","params":{"protocolVersion":"2025-11-25"}},folder)
    assert init["result"]["serverInfo"]["name"]=="human2api"
    assert handle_message({"jsonrpc":"2.0","method":"notifications/initialized"},folder) is None
    tools=handle_message({"jsonrpc":"2.0","id":5,"method":"tools/list"},folder)["result"]["tools"]
    assert "h2a_create_invoice" in [t["name"] for t in tools]
    assert tools[1]["inputSchema"]["properties"]["amount"]["type"]=="number"
    blocked=handle_message({"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"h2a_create_invoice","arguments":{"customer_name":"X","amount":4}}},folder)
    assert blocked["result"]["isError"] is True


def test_openapi_is_valid_shape(demo_flow):
    _,_,folder,url=demo_flow
    spec=openapi_schema(folder)
    assert spec["openapi"]=="3.1.0"
    assert spec["paths"]["/api/run/create_invoice"]["post"]["security"]
    assert spec["components"]["securitySchemes"]["LocalToken"]["name"]=="X-H2A-Token"


def test_dashboard_assets(demo_flow):
    _,server,_,url=demo_flow
    for path in ["/", "/app.js", "/app.css", "/demo", "/demo.css", "/demo.js"]:
        with urlopen(url+path,timeout=5) as response:
            assert response.status==200 and len(response.read())>200
    with urlopen(url,timeout=5) as response:
        page=response.read().decode()
    assert server.token in page
    assert '__H2A_LOCAL_TOKEN__' not in page


def test_mcp_over_real_stdio(demo_flow):
    _,_,directory,_=demo_flow
    import os
    env=os.environ.copy()
    env['PYTHONPATH']=str(__import__('pathlib').Path(__file__).parents[1]/'src')
    proc=subprocess.Popen([sys.executable,'-m','human2api','mcp','--directory',str(directory)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env)
    try:
        proc.stdin.write(json.dumps({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25'}})+'\n')
        proc.stdin.write(json.dumps({'jsonrpc':'2.0','id':2,'method':'tools/list'})+'\n')
        proc.stdin.flush()
        init=json.loads(proc.stdout.readline())
        tools=json.loads(proc.stdout.readline())
        assert init['result']['serverInfo']['name']=='human2api'
        assert any(x['name']=='h2a_create_invoice' for x in tools['result']['tools'])
    finally:
        proc.terminate()
        proc.communicate(timeout=4)
