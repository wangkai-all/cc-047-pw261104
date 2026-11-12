"""Test fixtures: isolated DATA_DIR in a temp path, no per-row delay.

Env vars are set BEFORE importing app.config, so every module picks up the
ephemeral database and storage locations.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

_TMP = tempfile.mkdtemp(prefix="ws-demo-test-")
os.environ["APP_DATA_DIR"] = str(Path(_TMP) / "data")
os.environ["IMPORT_ROW_DELAY"] = "0"

# Make `backend/` importable when pytest is run from the repo root.
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app import config, db  # noqa: E402
from app.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="session")
def client():
    config.ensure_dirs()
    db.init_db()
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _clean_tables():
    """Each test starts with empty tables and an empty storage dir."""
    import shutil

    conn = db.get_conn()
    conn.execute("DELETE FROM records")
    conn.execute("DELETE FROM import_tasks")
    conn.commit()
    if config.STORAGE_DIR.exists():
        shutil.rmtree(config.STORAGE_DIR)
    config.ensure_dirs()
    yield


@pytest.fixture
def alpha_headers():
    return {"X-Workspace-Id": "ws-alpha"}


@pytest.fixture
def beta_headers():
    return {"X-Workspace-Id": "ws-beta"}


@pytest.fixture
def mapping():
    return {"order_id": "order_id", "customer": "customer",
            "amount": "amount", "remark": "remark"}


SAMPLES = Path(__file__).resolve().parents[2] / "samples"


@pytest.fixture
def alpha_file():
    return SAMPLES / "ws-alpha" / "orders.csv"


@pytest.fixture
def beta_file():
    return SAMPLES / "ws-beta" / "orders.csv"


def upload(client, ws_headers, request_id, path, mapping):
    with open(path, "rb") as fh:
        return client.post(
            "/api/imports",
            headers=ws_headers,
            data={"request_id": request_id, "mapping": __import__("json").dumps(mapping)},
            files={"file": (path.name, fh, "text/csv")},
        )


@pytest.fixture
def uploader():
    return upload


@pytest.fixture
def wait_terminal():
    def _wait(client, ws_headers, task_id, timeout=10.0):
        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            r = client.get(f"/api/imports/{task_id}", headers=ws_headers)
            status = r.json()["status"]
            if status not in ("pending", "running"):
                return r.json()
            time.sleep(0.02)
        raise AssertionError("task did not finish in time")
    return _wait
