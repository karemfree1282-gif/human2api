"""Reproducible, synthetic, loopback-only load and cancellation probe.

No real accounts, browser URLs, devices, public hosting or network attacks.
Observed latency is specific to the test machine, not a performance promise.
"""
from __future__ import annotations
import argparse
import json
import statistics
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from human2api.http_server import make_server
from human2api.models import save_workflow
from human2api.registry import make_registry


def run(requests: int = 1000, workers: int = 16) -> dict:
    if not 1 <= requests <= 10000 or not 1 <= workers <= 24:
        raise ValueError('use 1-10000 requests and 1-24 workers')
    with tempfile.TemporaryDirectory(prefix='h2a-local-soak-') as temp:
        folder = Path(temp) / 'workflows'; folder.mkdir()
        wf = {'schemaVersion': 1, 'name': 'qa_wait', 'description': 'Synthetic cooperative wait',
              'target': 'desktop', 'permissions': 'read', 'steps': [{'action': 'wait_ms', 'durationMs': 5000}]}
        save_workflow(folder / 'qa_wait.json', wf)
        local = make_server(folder, 0); registry = make_registry(Path(temp) / 'registry', 0)
        origin = f'http://127.0.0.1:{local.server_address[1]}'
        threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (local, registry)]
        for t in threads: t.start()
        def request(url, body=None, token=None):
            headers = {'Content-Type': 'application/json'}
            if token: headers['X-H2A-Token'] = token
            with urlopen(Request(url, data=None if body is None else json.dumps(body).encode(), headers=headers), timeout=15) as r:
                return r.status, json.load(r)
        try:
            measures = []
            for service, url, token in [('local-rest', origin + '/api/workflows', local.token),
                                        ('registry', registry.public_origin + '/v1/packages', None)]:
                def job(_):
                    start = time.monotonic(); status, body = request(url, token=token)
                    assert status == 200
                    return (time.monotonic() - start) * 1000
                start = time.monotonic()
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    elapsed = list(pool.map(job, range(requests)))
                duration = time.monotonic() - start
                ordered = sorted(elapsed)
                measures.append({'service': service, 'requests': requests, 'workers': workers,
                                 'successful': len(elapsed), 'errors': 0, 'durationSeconds': round(duration, 3),
                                 'requestsPerSecond': round(requests / duration, 2),
                                 'latencyP50Ms': round(statistics.median(elapsed), 2),
                                 'latencyP95Ms': round(ordered[min(len(ordered)-1, int(len(ordered)*.95))], 2)})
            def await_state(rid, expected):
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    state = request(origin + f'/api/runs/{rid}', token=local.token)[1]['state']
                    if state == expected: return
                    time.sleep(.02)
                raise AssertionError(f'expected {expected}, received {state}')
            first = request(origin + '/api/run/qa_wait', {'inputs': {}}, local.token)[1]['runId']
            await_state(first, 'running')
            competing = request(origin + '/api/run/qa_wait', {'inputs': {}}, local.token)[1]['runId']
            await_state(competing, 'failed')  # An exclusive desktop device lease prevents overlap.
            cancel_start = time.monotonic()
            assert request(origin + f'/api/runs/{first}/cancel', {}, local.token)[0] == 202
            await_state(first, 'cancelled')
            restart = request(origin + '/api/run/qa_wait', {'inputs': {}}, local.token)[1]['runId']
            await_state(restart, 'running')  # The earlier lease and slots were released.
            assert request(origin + f'/api/runs/{restart}/cancel', {}, local.token)[0] == 202
            await_state(restart, 'cancelled')
            assert request(origin + '/health')[0] == 200
            return {'status': 'passed', 'scope': 'local synthetic service soak only', 'publicHostingVerified': False,
                    'requests': measures, 'exclusiveDesktopLeaseVerified': True, 'cancelledRuns': 2,
                    'cancellationSeconds': round(time.monotonic()-cancel_start, 3),
                    'notes': 'No browser URL navigation or physical-device acceptance is claimed.'}
        finally:
            for server in (local, registry): server.shutdown(); server.server_close()
            for thread in threads: thread.join(5)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--requests', type=int, default=1000)
    parser.add_argument('--workers', type=int, default=16)
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    result = run(options.requests, options.workers)
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
