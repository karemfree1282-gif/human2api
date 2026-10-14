import unittest
from human2api.server_limits import DeviceLeaseManager, RateLimiter

class TestNewCapabilitiesLimits(unittest.TestCase):
    def test_device_lease_exclusivity(self) -> None:
        mgr = DeviceLeaseManager()
        self.assertTrue(mgr.acquire("desktop_pointer", ttl_seconds=10.0))
        self.assertFalse(mgr.acquire("desktop_pointer", ttl_seconds=10.0))
        mgr.release("desktop_pointer")
        self.assertTrue(mgr.acquire("desktop_pointer", ttl_seconds=10.0))
