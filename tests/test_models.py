import unittest
from human2api.models import Workflow, WorkflowStep, InputSpec

class TestModelsUnit(unittest.TestCase):
    def test_workflow_requires_write_detection(self) -> None:
        wf_read = Workflow(name="ReadOnly", target="browser", mode="read", steps=[WorkflowStep(action="goto", url="http://127.0.0.2/demo")])
        self.assertFalse(wf_read.requires_write_approval())
        wf_write = Workflow(name="WriteStep", target="browser", mode="read", steps=[WorkflowStep(action="click", selector="#b", isWriteAction=True)])
        self.assertTrue(wf_write.requires_write_approval())
