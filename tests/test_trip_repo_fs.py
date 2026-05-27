import pytest
from app import config
from app.models_trip import Trip, TripDates
from app.services import trip_repo
from app.services.trip_repo import FilesystemTripRepo, SchemaVersionError


def _trip(slug="balsam-lake-2026-05"):
    return Trip(schema_version=1, name=slug, park="balsam-lake", mode="car_camping",
                dates=TripDates(start="2026-05-30", end="2026-05-31"))


def test_save_get_exists_roundtrip(tmp_path):
    repo = FilesystemTripRepo(tmp_path)
    assert repo.exists("x") is False
    assert repo.get("x") is None
    repo.save("x", _trip("x"))
    assert repo.exists("x") is True
    got = repo.get("x")
    assert got.park == "balsam-lake" and got.mode == "car_camping"


def test_list_slugs_sorted(tmp_path):
    repo = FilesystemTripRepo(tmp_path)
    repo.save("b", _trip("b"))
    repo.save("a", _trip("a"))
    assert repo.list_slugs() == ["a", "b"]


def test_delete(tmp_path):
    repo = FilesystemTripRepo(tmp_path)
    repo.save("x", _trip("x"))
    repo.delete("x")
    assert repo.exists("x") is False


def test_routes_roundtrip(tmp_path):
    repo = FilesystemTripRepo(tmp_path)
    repo.save("x", _trip("x"))
    assert repo.get_routes("x") is None
    repo.set_routes("x", [{"name": "leg1"}])
    assert repo.get_routes("x") == [{"name": "leg1"}]


def test_bad_schema_version_raises(tmp_path):
    d = tmp_path / "x"
    d.mkdir()
    (d / "trip.json").write_text('{"schema_version": 99, "name": "x", "park": "p",'
                                 ' "dates": {"start": "2026-05-30", "end": "2026-05-31"}}')
    with pytest.raises(SchemaVersionError):
        FilesystemTripRepo(tmp_path).get("x")


def test_get_repo_filesystem_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STORAGE_BACKEND", "filesystem")
    monkeypatch.setattr(config, "TRIPS_DIR", tmp_path)
    repo = trip_repo.get_repo()
    assert isinstance(repo, FilesystemTripRepo)
    repo.save("x", _trip("x"))
    assert trip_repo.get_repo().get("x").park == "balsam-lake"
