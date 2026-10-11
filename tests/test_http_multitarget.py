import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from human2api.models import save_workflow


def json_call(url, token, path):
    req = Request(url + path, headers={'X-H2A-Token':token})
    with urlopen(req,timeout=3) as response:
        return json.load(response)


def test_api_platform_catalog_and_openapi(local_server):
    server, folder, url = local_server
    platforms = json_call(url, server.token, '/api/platforms')
    assert 'android' in platforms and 'desktop' in platforms
    assert json_call(url, server.token, '/api/catalog') == {'packages': []}
    schema = json_call(url, server.token, '/api/openapi.json')
    assert schema['openapi'] == '3.1.0'


def test_get_platforms_rejects_no_token(local_server):
    server, folder, url = local_server
    try:
        json_call(url, '', '/api/platforms')
        assert False, 'Expected 401'
    except HTTPError as exc:
        assert exc.code == 401


def test_multi_target_schema_in_openapi(local_server):
    server, folder, url = local_server
    save_workflow(folder/'phone.json', {
        'schemaVersion':1, 'name':'phone', 'description':'Take a screenshot',
        'target':'android', 'permissions':'read', 'inputs':{},
        'steps':[{'action':'screenshot'}],
    })
    schema = json_call(url, server.token, '/api/openapi.json')
    info = schema['paths']['/api/run/phone']['post']['requestBody']['content']['application/json']['schema']
    assert 'aiHeal' in info['properties']
    assert 'approve' in info['properties']


def test_public_catalog_view_is_token_protected_and_read_only(local_server, monkeypatch):
    server, folder, url = local_server
    from human2api import http_server
    from unittest.mock import Mock
    fake = Mock(return_value=[{"name": "create_invoice", "target": "browser", "description": "Sample"}])
    monkeypatch.setattr(http_server, "remote_catalog", fake)
    data = json_call(url, server.token, "/api/catalog/remote")
    assert data["packages"][0]["name"] == "create_invoice"
    fake.assert_called_once()
    try:
        json_call(url, "", "/api/catalog/remote")
    except HTTPError as exc:
        assert exc.code == 401
    else:
        raise AssertionError("unauthenticated remote catalog request was accepted")
