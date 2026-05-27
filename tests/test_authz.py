import pytest
from app.models_trip import Trip, TripDates
from app.services import authz
from app.services.identity import User


def _trip(owner):
    return Trip(schema_version=1, name="t", park="p", owner_id=owner,
                dates=TripDates(start="2026-05-30", end="2026-05-31"))


def test_owner_or_communal_allowed():
    assert authz.can_edit_core(_trip("uid-1"), User("uid-1", "")) is True
    assert authz.can_edit_core(_trip(None), User("uid-2", "")) is True   # communal


def test_non_owner_blocked_from_core():
    assert authz.can_edit_core(_trip("uid-1"), User("uid-2", "")) is False


def test_meta_body_core_vs_participants():
    assert authz.meta_touches_core({"participants": []}) is False
    assert authz.meta_touches_core({"park": "x"}) is True
    assert authz.meta_touches_core({"participants": [], "dates": {}}) is True


def test_route_non_owner_blocked_from_delete(monkeypatch, tmp_path):
    import app.config as config
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services import identity
    monkeypatch.setattr(config, "STORAGE_BACKEND", "filesystem")
    monkeypatch.setattr(config, "TRIPS_DIR", tmp_path)
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    monkeypatch.setattr(identity, "current_user", lambda req: User("intruder", "x"))
    from app.services import trips as trips_svc
    trips_svc.create_trip_v2("balsam-lake", "2026-05-30", "2026-05-31", [], owner_id="owner-1")
    c = TestClient(app)
    assert c.delete("/api/trips/balsam-lake-2026-05").status_code == 403


def test_route_non_owner_can_edit_gear(monkeypatch, tmp_path):
    import app.config as config
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services import identity
    monkeypatch.setattr(config, "STORAGE_BACKEND", "filesystem")
    monkeypatch.setattr(config, "TRIPS_DIR", tmp_path)
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    monkeypatch.setattr(identity, "current_user", lambda req: User("friend", "f"))
    from app.services import trips as trips_svc
    trips_svc.create_trip_v2("balsam-lake", "2026-05-30", "2026-05-31", [], owner_id="owner-1")
    c = TestClient(app)
    r = c.put("/api/trips/balsam-lake-2026-05/section/gear", json=[])
    assert r.status_code == 200   # friends may edit planning lists


def test_access_point_is_core():
    assert authz.meta_touches_core({"access_point": "x"}) is True


def test_route_non_owner_blocked_from_core_meta(monkeypatch, tmp_path):
    import app.config as config
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services import identity
    from app.services.identity import User
    monkeypatch.setattr(config, "STORAGE_BACKEND", "filesystem")
    monkeypatch.setattr(config, "TRIPS_DIR", tmp_path)
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    monkeypatch.setattr(identity, "current_user", lambda req: User("intruder", "x"))
    from app.services import trips as trips_svc
    trips_svc.create_trip_v2("balsam-lake", "2026-05-30", "2026-05-31", [], owner_id="owner-1")
    c = TestClient(app)
    assert c.patch("/api/trips/balsam-lake-2026-05/meta", json={"park": "x"}).status_code == 403
    # participants-only still allowed for a friend:
    assert c.patch("/api/trips/balsam-lake-2026-05/meta", json={"participants": ["Bob"]}).status_code == 200
