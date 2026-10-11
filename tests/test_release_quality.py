"""Non-networked release regression checks."""
import copy
import json
from pathlib import Path

import pytest

from human2api.mcp_server import handle_message
from human2api.models import WorkflowError, validate_inputs, validate_workflow
from human2api.recorder import workflow_from_events
from human2api.runner import _safe_navigation


def test_no_script_or_navigate_injection(sample):
    payload = copy.deepcopy(sample)
    payload['steps'] = [{'action': 'navigate', 'url': 'javascript:alert(1)'}]
    # Static navigation URLs are validated at runtime with the allowedHosts policy.
    validate_workflow(payload)
    with pytest.raises(WorkflowError):
        _safe_navigation('javascript:alert(1)', {'localhost'})


def test_no_cross_domain_navigation(sample):
    with pytest.raises(WorkflowError, match='outside allowedHosts'):
        _safe_navigation('https://example.org/', {'localhost'})


def test_filename_traversal_is_rejected(sample):
    payload = copy.deepcopy(sample)
    payload['steps'].append({'action': 'screenshot', 'filename': '../../outside'})
    with pytest.raises(WorkflowError, match='filename'):
        validate_workflow(payload)


def test_invalid_boolean_input_rejected(sample):
    sample['inputs']['customer_name']['type'] = 'boolean'
    with pytest.raises(WorkflowError, match='must be boolean'):
        validate_inputs(sample, {'customer_name': 'true', 'amount': 20})


def test_recorder_strips_credentials_from_start_url():
    events = [{'action': 'click', 'selector': '#go'}]
    workflow = workflow_from_events('test_flow', 'Example', 'https://example.com/demo?token=never-save#secret', events)
    dumped = json.dumps(workflow)
    assert 'never-save' not in dumped
    assert '#secret' not in dumped
    assert workflow['startUrl'] == 'https://example.com/demo'


def test_mcp_unknown_tool_is_a_structured_error(tmp_path):
    result = handle_message({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'h2a_unsafe_name', 'arguments': {}}}, tmp_path)
    assert result['result']['isError'] is True


def test_samples_license_readme_present():
    root = Path(__file__).resolve().parents[1]
    for relative in ['README.md', 'LICENSE', 'SECURITY.md', 'docs/FAQ.md', 'docs/index.html', '.github/workflows/ci.yml', '.github/workflows/pages.yml', '.github/workflows/codeql.yml']:
        assert (root / relative).is_file(), relative


def test_no_saved_defaults_for_passwords(sample):
    sample['inputs']['customer_name']['secret'] = True
    sample['inputs']['customer_name']['default'] = 'user-password'
    with pytest.raises(WorkflowError):
        validate_workflow(sample)
