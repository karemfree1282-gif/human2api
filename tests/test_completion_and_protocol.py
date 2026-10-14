import unittest
from human2api.completion import check_dependencies_and_toolchains

class TestCompletionChecks(unittest.TestCase):
    def test_dependency_checks_return_structured_items(self) -> None:
        items = check_dependencies_and_toolchains()
        names = {i.name for i in items}
        self.assertIn("python_core_and_browser_deps", names)
        self.assertIn("chromium_browser_binary", names)
