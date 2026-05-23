import json
from pathlib import Path

import pytest

from app.models_trip import Trip
from app.services import trip_store


@pytest.fixture
def sample_trip_dict():
    return {
        "schema_version": 1,
        "name": "test-2026-05",
        "park": "killarney",
        "dates": {"start": "2026-05-15", "end": "2026-05-18"},
        "participants": ["Alex"],
        "access_point": "George Lake",
        "nights": [],
        "itinerary": [],
        "gear": [],
        "food": [],
        "costs": [],
    }


def test_load_reads_and_validates(tmp_path, sample_trip_dict):
    trip_dir = tmp_path / "test-2026-05"
    trip_dir.mkdir()
    (trip_dir / "trip.json").write_text(json.dumps(sample_trip_dict))
    trip = trip_store.load(trip_dir)
    assert isinstance(trip, Trip)
    assert trip.name == "test-2026-05"


def test_save_writes_indented_json(tmp_path, sample_trip_dict):
    trip_dir = tmp_path / "test-2026-05"
    trip_dir.mkdir()
    trip = Trip.model_validate(sample_trip_dict)
    trip_store.save(trip_dir, trip)
    on_disk = json.loads((trip_dir / "trip.json").read_text())
    assert on_disk["name"] == "test-2026-05"
    raw = (trip_dir / "trip.json").read_text()
    assert raw.startswith("{\n")  # pretty-printed


def test_load_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        trip_store.load(tmp_path / "nope")


def test_load_rejects_unknown_schema_version(tmp_path, sample_trip_dict):
    sample_trip_dict["schema_version"] = 99
    trip_dir = tmp_path / "test-2026-05"
    trip_dir.mkdir()
    (trip_dir / "trip.json").write_text(json.dumps(sample_trip_dict))
    with pytest.raises(trip_store.SchemaVersionError):
        trip_store.load(trip_dir)
