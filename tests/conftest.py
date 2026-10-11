import copy
import os
import shutil
import threading
from pathlib import Path

import pytest

from human2api.http_server import make_server
from human2api.models import load_workflow, save_workflow


@pytest.fixture
def sample():
    return copy.deepcopy(load_workflow(Path(__file__).parent.parent / "workflows" / "create_invoice.json"))


@pytest.fixture
def local_server(tmp_path):
    folder = tmp_path / "workflows"
    folder.mkdir()
    server = make_server(folder, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    yield server, folder, url
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)


@pytest.fixture
def demo_flow(sample, local_server):
    server, folder, url = local_server
    sample["startUrl"] = url + "/demo"
    save_workflow(folder / "create_invoice.json", sample)
    return sample, server, folder, url


@pytest.fixture
def chromium_path():
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        return None  # Prefer the Playwright-managed browser on CI.
    return shutil.which("chromium") or shutil.which("google-chrome")
