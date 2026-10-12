"""Schema/CLI contract checks shared by local builds and release CI."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from human2api import __version__
from human2api.models import WorkflowError, validate_workflow

ROOT=Path(__file__).resolve().parents[1]


def test_release_metadata_stays_in_sync():
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    package=tomllib.loads((ROOT/"pyproject.toml").read_text())
    assert package["project"]["version"] == __version__
    assert __version__ in (ROOT/"CHANGELOG.md").read_text()
    assert "__H2A_LOCAL_TOKEN__" in (ROOT/"src/human2api/static/dashboard.html").read_text()


def test_schema_parity_for_new_and_old_workflows():
    schema=json.loads((ROOT/"schemas/workflow.schema.json").read_text())
    jsonschema=pytest.importorskip("jsonschema")
    for path in sorted((ROOT/"workflows").glob("*.json")):
        value=json.loads(path.read_text())
        validate_workflow(value)
        jsonschema.validate(value, schema)
    sample={"schemaVersion":1,"name":"desktop_reader","description":"Inspect stable UI",
        "target":"desktop","permissions":"read","steps":[
          {"action":"ui_assert_text","windowTitle":"Notes","automationId":"txt","text":"Saved","retries":1,"retryDelayMs":250}]}
    validate_workflow(sample)
    jsonschema.validate(sample,schema)
    wrong=copy.deepcopy(sample)
    wrong["steps"][0]["retries"]=7
    with pytest.raises(WorkflowError): validate_workflow(wrong)
    with pytest.raises(jsonschema.ValidationError): jsonschema.validate(wrong,schema)


def test_plan_is_safe_and_never_prints_value():
    proc=subprocess.run([sys.executable,"-m","human2api","plan","create_invoice", "--directory",str(ROOT/"workflows"),
       "--data",'{"customer_name":"PRIVATE_IDENTIFIER_123","amount":24.3}'],capture_output=True,text=True,timeout=15)
    assert proc.returncode==0,proc.stderr
    assert "PRIVATE_IDENTIFIER_123" not in proc.stdout
    assert json.loads(proc.stdout)["executed"] is False


def test_public_docs_explain_unverified_hardware():
    readme=(ROOT/"README.md").read_text()
    assert "not" in readme.lower() and "hardware" in readme.lower()
    assert "--trust-key" in readme and "h2a scheduler" in readme
