import unittest
from human2api.server_limits import RateLimiter

class TestReleaseAcceptanceLimits(unittest.TestCase):
    def test_rate_limiter_enforces_window_cap(self) -> None:
        rl = RateLimiter(max_requests_per_window=2, window_seconds=10.0, max_concurrent=4)
        self.assertTrue(rl.try_enter_request("127.0.0.1"))
        rl.exit_request()
        self.assertTrue(rl.try_enter_request("127.0.0.1"))
        rl.exit_request()
        self.assertFalse(rl.try_enter_request("127.0.0.1"))
