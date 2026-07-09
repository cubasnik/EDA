import socket
import threading
import time

import pytest
import requests
import uvicorn

from eda.config import settings
from eda.core import store as store_module


@pytest.fixture(autouse=True)
def fast_engine_and_isolated_db(tmp_path, monkeypatch):
    """Speed up the simulated workflow engine and isolate each test's DB."""
    monkeypatch.setattr(settings, "STEP_MIN_DELAY", 0.01)
    monkeypatch.setattr(settings, "STEP_MAX_DELAY", 0.02)

    db_path = tmp_path / "eda-test.db"
    monkeypatch.setattr(settings, "DB_PATH", str(db_path))

    store_module.reset_store()
    yield
    store_module.reset_store()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live_server():
    """Run the real FastAPI app over HTTP so eda-cli can be exercised end to end."""
    from eda.api.main import app

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            requests.get(base_url + "/health", timeout=0.2)
            break
        except requests.RequestException:
            time.sleep(0.05)
    else:
        raise RuntimeError("live_server did not start in time")

    yield base_url

    server.should_exit = True
    thread.join(timeout=5)
