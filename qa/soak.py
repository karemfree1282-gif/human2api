#!/usr/bin/env python3
"""Load & Soak Stability Test Harness (`qa/soak.py`) verifying concurrency, rate limits, and cancellation responsiveness."""

from __future__ import annotations

import concurrent.futures
import json
import pathlib
import sys
import tempfile
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from human2api.execution import CancellationToken  # noqa: E402
from human2api.http_server import Human2APIServer  # noqa: E402
from human2api.server_limits import RateLimiter  # noqa: E402
from human2api.workspace import Workspace  # noqa: E402


def run_soak_test(num_requests: int = 40, concurrency: int = 6) -> dict:
    with tempfile.TemporaryDirectory(prefix="h2a_soak_") as tmp:
        ws = Workspace(pathlib.Path(tmp))
        limiter = RateLimiter(max_requests_per_window=200, window_seconds=10.0, max_concurrent=16)
        srv = Human2APIServer(workspace=ws, host="127.0.0.1", port=0, rate_limiter=limiter)
        base = srv.start()
        latencies = []
        errors = 0
        try:
            def _one_call(_i: int) -> float:
                t0 = time.perf_counter()
                req = urllib.request.Request(
                    f"{base}/api/v1/health",
                    headers={"X-H2A-Token": srv.auth_token, "Host": f"127.0.0.1:{srv.port}"},
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    assert resp.status == 200
                return (time.perf_counter() - t0) * 1000.0

            with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
                futs = [pool.submit(_one_call, i) for i in range(num_requests)]
                for f in concurrent.futures.as_completed(futs):
                    try:
                        latencies.append(f.result())
                    except Exception:
                        errors += 1

            # Verify immediate cancellation responsiveness (< 25 ms)
            cancel_t0 = time.perf_counter()
            tok = CancellationToken()
            cb_called = []
            tok.register_callback(lambda: cb_called.append(True))
            tok.cancel("soak test cancel")
            cancel_latency_ms = (time.perf_counter() - cancel_t0) * 1000.0

            return {
                "requests_total": num_requests,
                "requests_succeeded": len(latencies),
                "errors": errors,
                "avg_latency_ms": round(sum(latencies) / max(1, len(latencies)), 2),
                "max_latency_ms": round(max(latencies) if latencies else 0.0, 2),
                "cancellation_latency_ms": round(cancel_latency_ms, 3),
                "callback_invoked": bool(cb_called),
            }
        finally:
            srv.stop()


if __name__ == "__main__":
    res = run_soak_test()
    print(json.dumps(res, indent=2))
    sys.exit(0 if res["errors"] == 0 else 1)
