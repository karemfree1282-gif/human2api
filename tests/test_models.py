import copy
import json

import pytest

from human2api.models import WorkflowError, input_json_schema, list_workflows, load_workflow, save_workflow, template, validate_inputs, validate_workflow, workflow_file
from human2api.recorder import variable_name, workflow_from_events


def test_sample_is_valid(sample):
    validate_workflow(sample)
    assert len(sample["steps"]) == 6


def test_schema_and_inputs(sample):
    assert input_json_schema(sample)["required"] == ["customer_name", "amount"]
    assert validate_inputs(sample, {"customer_name": "Ana", "amount": 13.6})["amount"] == 13.6
    with pytest.raises(WorkflowError, match="required"):
        validate_inputs(sample, {"amount": 1})
    with pytest.raises(WorkflowError, match="unknown"):
        validate_inputs(sample, {"customer_name": "A", "amount": 1, "debug": 3})
    with pytest.raises(WorkflowError, match="finite number"):
        validate_inputs(sample, {"customer_name": "Ana", "amount": float("inf")})
    with pytest.raises(WorkflowError, match="finite number"):
        validate_inputs(sample, {"customer_name": "Ana", "amount": float("nan")})
    with pytest.raises(WorkflowError):
        validate_inputs(sample, {"customer_name": "Ana", "amount": True})


def test_template_substitution():
    assert template("https://app.com/{{ user }}?force={{flag}}", {"user": "ana", "flag": True}) == "https://app.com/ana?force=true"
    with pytest.raises(WorkflowError):
        template("{{missing}}", {})


def test_no_arbitrary_code(sample):
    clone=copy.deepcopy(sample)
    clone["steps"] = [{"action": "javascript", "code": "alert(1)"}]
    with pytest.raises(WorkflowError, match="unrecognized action"):
        validate_workflow(clone)


def test_host_constraints(sample):
    clone=copy.deepcopy(sample)
    clone["startUrl"] = "file:///etc/passwd"
    with pytest.raises(WorkflowError):
        validate_workflow(clone)
    clone["startUrl"]="https://other-site.example/"
    with pytest.raises(WorkflowError, match="allowedHosts"):
        validate_workflow(clone)


def test_path_traversal_rejected():
    for name in ["../foo", "--name", "x/a", "a.json", "mcp*", "abc def"]:
        with pytest.raises(WorkflowError):
            workflow_file("workflows",name)


def test_save_load_and_list(sample,tmp_path):
    file=save_workflow(tmp_path / "create_invoice.json", sample)
    assert load_workflow(file)["name"]=="create_invoice"
    assert list_workflows(tmp_path)[0]["steps"]==6
    with pytest.raises(WorkflowError):
        save_workflow(tmp_path / "invalid.json", {"invalid": 1})


def test_secret_defaults_forbidden(sample):
    clone=copy.deepcopy(sample)
    clone["inputs"]["customer_name"]["secret"]=True
    clone["inputs"]["customer_name"]["default"]="top secret"
    with pytest.raises(WorkflowError, match="secret inputs"):
        validate_workflow(clone)


def test_recorder_discards_values():
    events=[
      {"action":"fill","selector":"#email","field":"email","inputType":"email","value":"nobody@example.com"},
      {"action":"fill","selector":"#pw","field":"password","inputType":"password","value":"dont-record-me"},
      {"action":"click","selector":"#submit"}
    ]
    data=workflow_from_events("login_app","Sign in","https://example.com/login?key=do-not-store#fragment",events)
    dump=json.dumps(data)
    assert "nobody@example.com" not in dump and "dont-record-me" not in dump
    assert "do-not-store" not in dump
    assert "password" in data["inputs"]
    assert data["inputs"]["password"]["secret"] is True
    assert data["steps"][0]["value"] == "{{email}}"
    validate_workflow(data)


def test_recorder_reuses_variable_name():
    events=[{"action":"fill","selector":"#a","field":"some field"},{"action":"fill","selector":"#b","field":"some field"}]
    wf=workflow_from_events("example","Example","https://example.com",events)
    assert len(wf["inputs"])==1
    assert wf["steps"][0]["value"]==wf["steps"][1]["value"]
    assert variable_name("42 times",set())=="field_42_times"


def test_read_workflows_cannot_contain_click(sample):
    sample['permissions']='read'
    with pytest.raises(WorkflowError, match='read-only'):
        validate_workflow(sample)


def test_unexpected_step_fields_rejected(sample):
    sample['steps'][0]['python_code']='import os'
    with pytest.raises(WorkflowError, match='unknown fields'):
        validate_workflow(sample)
