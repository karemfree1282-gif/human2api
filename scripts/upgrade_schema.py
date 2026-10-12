"""Generate the JSON schema from the same action contracts used at runtime."""
import json
from pathlib import Path
from human2api.contracts import workflow_schema

path = Path(__file__).resolve().parents[1] / "schemas/workflow.schema.json"
path.write_text(json.dumps(workflow_schema(), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
print("Generated target-aware workflow schema")
