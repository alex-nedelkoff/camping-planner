import json
from pathlib import Path

import pytest

from app.services import route_cache, db


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    p = tmp_path / "x.sqlite3"
    db.init_schema(p)
    monkeypatch.setattr(db, "DATABASE_PATH", p)
    return p


def test_route_cache_uses_provider_then_caches(tmp_path, tmp_db):
    routes_path = tmp_path / "manual_routes.json"
    routes_path.write_text(json.dumps([{"name": "a"}]))
    calls = []

    def fake_provider(routes_payload, trip_slug):
        calls.append(routes_payload)
        return {"html": "<div>map</div>", "distance_km": 12.3}

    out1 = route_cache.get_route_render(routes_path, "k-2026-05",
                                        provider=fake_provider)
    out2 = route_cache.get_route_render(routes_path, "k-2026-05",
                                        provider=fake_provider)
    assert out1 == out2
    assert len(calls) == 1  # second call hit cache


def test_route_cache_invalidates_on_routes_change(tmp_path, tmp_db):
    routes_path = tmp_path / "manual_routes.json"
    routes_path.write_text(json.dumps([{"name": "a"}]))
    calls = []
    def fake(payload, slug):
        calls.append(payload)
        return {"html": str(len(calls)), "distance_km": 0}
    route_cache.get_route_render(routes_path, "x", provider=fake)
    routes_path.write_text(json.dumps([{"name": "b"}]))
    route_cache.get_route_render(routes_path, "x", provider=fake)
    assert len(calls) == 2
