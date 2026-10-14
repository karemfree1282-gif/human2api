import pathlib, unittest, json

class TestSchemaAndReleaseCompatibility(unittest.TestCase):
    def test_workflow_schema_has_required_defs(self) -> None:
        root = pathlib.Path(__file__).resolve().parents[1]
        schema = json.loads((root / "schemas" / "workflow.schema.json").read_text(encoding="utf-8"))
        self.assertIn("workflowStep", schema["$defs"])
        self.assertIn("assertionSpec", schema["$defs"])
        self.assertIn("healingConfig", schema["$defs"])
