import app.config as config
from fastapi.testclient import TestClient
from app.main import app
from app.services import identity
from app.services.identity import User


def test_checklist_is_per_user(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "STORAGE_BACKEND", "filesystem")
    monkeypatch.setattr(config, "TRIPS_DIR", tmp_path)
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    from app.services import trips as trips_svc
    trips_svc.create_trip_v2("balsam-lake", "2026-05-30", "2026-05-31", [], owner_id="o")
    slug = "balsam-lake-2026-05"
    c = TestClient(app)
    monkeypatch.setattr(identity, "current_user", lambda req: User("alice", "a"))
    c.post(f"/api/checklist?trip={slug}", json={"key": "tent", "checked": True})
    monkeypatch.setattr(identity, "current_user", lambda req: User("bob", "b"))
    r = c.get(f"/api/checklist?trip={slug}")
    assert r.json()["state"] == {}            # bob sees his own (empty)
    monkeypatch.setattr(identity, "current_user", lambda req: User("alice", "a"))
    r = c.get(f"/api/checklist?trip={slug}")
    assert r.json()["state"] == {"tent": True}  # alice sees hers
