import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import app  # noqa: E402


@pytest.fixture()
def client():
    with TestClient(app) as c:
        c.delete("/fault")
        yield c
        c.delete("/fault")


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_work_ok_without_fault(client):
    for _ in range(20):
        assert client.get("/work").status_code == 200


def test_fault_all_errors(client):
    client.post("/fault", json={"error_rate": 1.0, "extra_latency_ms": 0})
    for _ in range(10):
        assert client.get("/work").status_code == 500


def test_healthz_stays_ok_under_full_fault(client):
    client.post("/fault", json={"error_rate": 1.0})
    assert client.get("/healthz").status_code == 200


def test_fault_adds_latency(client):
    client.post("/fault", json={"error_rate": 0.0, "extra_latency_ms": 300})
    started = time.perf_counter()
    client.get("/work")
    assert time.perf_counter() - started >= 0.3


def test_fault_rate_is_validated(client):
    assert client.post("/fault", json={"error_rate": 1.5}).status_code == 422


def test_fault_can_be_cleared(client):
    client.post("/fault", json={"error_rate": 1.0})
    client.delete("/fault")
    assert client.get("/fault").json()["error_rate"] == 0.0


def test_metrics_exposed(client):
    client.get("/work")
    body = client.get("/metrics").text
    assert "stand_requests_total" in body
    assert "stand_request_duration_seconds_bucket" in body
    assert "stand_fault_error_rate" in body
