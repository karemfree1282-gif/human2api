import unittest
from human2api.runner import normalize_loopback_url_for_chromium

class TestBrowserExtendedHelpers(unittest.TestCase):
    def test_loopback_normalization_for_managed_chromium(self) -> None:
        self.assertEqual(normalize_loopback_url_for_chromium("http://127.0.0.1:8123/demo"), "http://127.0.0.2:8123/demo")
        self.assertEqual(normalize_loopback_url_for_chromium("http://localhost:9000/test"), "http://127.0.0.2:9000/test")
        self.assertEqual(normalize_loopback_url_for_chromium("https://example.com/a"), "https://example.com/a")
