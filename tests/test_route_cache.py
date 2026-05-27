import pytest

from app.services import cache, route_cache


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


class _StubRepo:
    def __init__(self, routes):
        self._routes = routes

    def get_routes(self, slug):
        return self._routes


def test_route_cache_uses_provider_then_caches(monkeypatch):
    stub = _StubRepo([{"name": "a"}])
    from app.services import trip_repo
    monkeypatch.setattr(trip_repo, "get_repo", lambda: stub)

    calls = []

    def fake_provider(routes_payload, trip_slug):
        calls.append(routes_payload)
        return {"html": "<div>map</div>", "distance_km": 12.3}

    out1 = route_cache.get_route_render("k-2026-05", provider=fake_provider)
    out2 = route_cache.get_route_render("k-2026-05", provider=fake_provider)
    assert out1 == out2
    assert len(calls) == 1  # second call hit cache


def test_route_cache_invalidates_on_routes_change(monkeypatch):
    from app.services import trip_repo
    routes = [{"name": "a"}]
    stub = _StubRepo(routes)
    monkeypatch.setattr(trip_repo, "get_repo", lambda: stub)

    calls = []

    def fake(payload, slug):
        calls.append(payload)
        return {"html": str(len(calls)), "distance_km": 0}

    route_cache.get_route_render("x", provider=fake)

    # Change routes — new content hash means cache miss
    stub._routes = [{"name": "b"}]
    route_cache.get_route_render("x", provider=fake)
    assert len(calls) == 2
