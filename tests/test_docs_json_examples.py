import pathlib, unittest
from human2api.completion import validate_docs_and_examples

class TestDocsJsonExamples(unittest.TestCase):
    def test_all_markdown_and_schema_json_blocks_are_valid(self) -> None:
        root = pathlib.Path(__file__).resolve().parents[1]
        res = validate_docs_and_examples(root)
        self.assertEqual(res.status, "passed", msg=res.details)
