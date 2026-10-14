import pathlib, tempfile, unittest
from human2api.models import Workflow, WorkflowStep

class TestWorkflowPersistence(unittest.TestCase):
    def test_save_and_load_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "wf.json"
            wf = Workflow(name="Roundtrip", target="browser", steps=[WorkflowStep(action="goto", url="http://127.0.0.2/demo")])
            wf.save(p)
            loaded = Workflow.load(p)
            self.assertEqual(loaded.name, "Roundtrip")
            self.assertEqual(len(loaded.steps), 1)
