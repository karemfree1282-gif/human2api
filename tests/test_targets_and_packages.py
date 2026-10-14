import pathlib, unittest
from human2api.models import Workflow

class TestTargetsAndPackagesExamples(unittest.TestCase):
    def test_all_bundled_examples_load_cleanly(self) -> None:
        root = pathlib.Path(__file__).resolve().parents[1]
        ex_dir = root / "src" / "human2api" / "examples"
        files = list(ex_dir.glob("*.json"))
        self.assertGreaterEqual(len(files), 4)
        for f in files:
            wf = Workflow.load(f)
            self.assertTrue(len(wf.steps) >= 1)
