"""Healthz endpoint."""

from fastapi.testclient import TestClient
from app.main import app


def test_healthz_returns_ok():
    r = TestClient(app).get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
