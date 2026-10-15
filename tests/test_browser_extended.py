"""Network-independent regression coverage for browser URL handling."""
import unittest
from unittest.mock import patch

from human2api.runner import normalize_loopback_url_for_chromium


class TestBrowserExtendedHelpers(unittest.TestCase):
    def test_keep_original_address_when_service_is_running_there(self):
        # Never break a working localhost server by forcing the .2 alias.
        with patch('human2api.runner.socket.create_connection'):
            self.assertEqual(
                normalize_loopback_url_for_chromium('http://127.0.0.1:8123/demo'),
                'http://127.0.0.1:8123/demo',
            )

    def test_unrelated_urls_are_never_rewritten(self):
        self.assertEqual(normalize_loopback_url_for_chromium('https://example.com/a'),
                         'https://example.com/a')
