import time
from app.services import cache


def setup_function(_):
    cache.clear()


def test_set_then_get_returns_payload():
    cache.set("weather_cache", ("balsam", "a", "b"), {"t": 1})
    assert cache.get("weather_cache", ("balsam", "a", "b"), ttl_seconds=100) == {"t": 1}


def test_get_missing_returns_none():
    assert cache.get("weather_cache", ("nope",), ttl_seconds=100) is None


def test_get_expired_returns_none(monkeypatch):
    cache.set("weather_cache", ("k",), {"v": 1})
    monkeypatch.setattr(cache, "_now", lambda: time.time() + 1000)
    assert cache.get("weather_cache", ("k",), ttl_seconds=10) is None


def test_namespaces_are_isolated():
    cache.set("weather_cache", ("k",), {"v": "w"})
    cache.set("availability_cache", ("k",), {"v": "a"})
    assert cache.get("availability_cache", ("k",), ttl_seconds=100) == {"v": "a"}


def test_drop_prefix_removes_matching_keys():
    cache.set("route_cache", ("trip-1", "h1"), {"v": 1})
    cache.set("route_cache", ("trip-1", "h2"), {"v": 2})
    cache.set("route_cache", ("trip-2", "h1"), {"v": 3})
    cache.drop_prefix("route_cache", ("trip-1",))
    assert cache.get("route_cache", ("trip-1", "h1"), ttl_seconds=100) is None
    assert cache.get("route_cache", ("trip-2", "h1"), ttl_seconds=100) == {"v": 3}
