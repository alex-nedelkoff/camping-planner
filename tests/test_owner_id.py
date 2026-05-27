import json
import app.config as config
import app.services.trips as trips_svc
from app.models_trip import Trip, TripDates


def test_trip_owner_id_defaults_none():
    t = Trip(schema_version=1, name="t", park="p",
             dates=TripDates(start="2026-05-30", end="2026-05-31"))
    assert t.owner_id is None


def test_create_trip_v2_sets_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STORAGE_BACKEND", "filesystem")
    monkeypatch.setattr(config, "TRIPS_DIR", tmp_path)
    slug = trips_svc.create_trip_v2(park="balsam-lake", start_date="2026-05-30",
                                    end_date="2026-05-31", participants=[], owner_id="uid-9")
    data = json.loads((tmp_path / slug / "trip.json").read_text())
    assert data["owner_id"] == "uid-9"
