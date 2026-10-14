import pathlib, tempfile, unittest
from human2api.contracts import WorkflowRunReport
from human2api.history import RunHistoryJournal

class TestHistoryJournal(unittest.TestCase):
    def test_history_redacts_secrets_and_bounds_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            j = RunHistoryJournal(pathlib.Path(tmp) / "hist.json", max_entries=5)
            for i in range(8):
                rep = WorkflowRunReport(
                    workflow_name=f"wf_{i}",
                    target="browser",
                    status="failed",
                    duration_ms=12.3,
                    error="Failed with MyTopSecretToken99",
                )
                j.record_run(rep, secret_values={"MyTopSecretToken99"})
            runs = j.list_runs()
            self.assertEqual(len(runs), 5)
            self.assertNotIn("MyTopSecretToken99", json_str := str(runs))
            self.assertIn("[REDACTED]", json_str)
            j.clear()
            self.assertEqual(len(j.list_runs()), 0)
