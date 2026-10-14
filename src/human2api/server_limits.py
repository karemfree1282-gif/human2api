"""Device Leases, Concurrency Controls, Request Size Limits, and Token-Bucket Rate Limiting."""

from __future__ import annotations

import threading
import time
from typing import Dict, Optional


class DeviceLeaseManager:
    """Ensures exclusive access to physical/UI targets (e.g. desktop pointer or Android device) so concurrent runs do not collide."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._leases: Dict[str, float] = {}

    def acquire(self, target_key: str, ttl_seconds: float = 60.0) -> bool:
        now = time.monotonic()
        with self._lock:
            exp = self._leases.get(target_key, 0.0)
            if exp > now:
                return False
            self._leases[target_key] = now + ttl_seconds
            return True

    def release(self, target_key: str) -> None:
        with self._lock:
            self._leases.pop(target_key, None)


class RateLimiter:
    """Per-client Token Bucket rate limiter and concurrent request limiter."""

    def __init__(
        self,
        max_requests_per_window: int = 60,
        window_seconds: float = 10.0,
        max_concurrent: int = 8,
        max_body_bytes: int = 262_144,  # 256 KiB
    ) -> None:
        self.max_requests_per_window = max_requests_per_window
        self.window_seconds = window_seconds
        self.max_concurrent = max_concurrent
        self.max_body_bytes = max_body_bytes
        self._lock = threading.Lock()
        self._counters: Dict[str, list] = {}
        self._active_concurrent = 0

    def try_enter_request(self, client_ip: str = "127.0.0.1") -> bool:
        now = time.monotonic()
        with self._lock:
            if self._active_concurrent >= self.max_concurrent:
                return False
            bucket = [ts for ts in self._counters.get(client_ip, []) if (now - ts) < self.window_seconds]
            if len(bucket) >= self.max_requests_per_window:
                self._counters[client_ip] = bucket
                return False
            bucket.append(now)
            self._counters[client_ip] = bucket
            self._active_concurrent += 1
            return True

    def exit_request(self) -> None:
        with self._lock:
            self._active_concurrent = max(0, self._active_concurrent - 1)
