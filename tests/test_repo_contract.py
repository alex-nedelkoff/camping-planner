import os
import pytest
from app.models_trip import Trip, TripDates
from app.services.trip_repo import FilesystemTripRepo

PG_URL = os.environ.get("TEST_DATABASE_URL")


def _trip(slug):
    return Trip(schema_version=1, name=slug, park="balsam-lake", mode="car_camping",
                dates=TripDates(start="2026-05-30", end="2026-05-31"))


def _make_pg_repo():
    import app.config as config
    config.DATABASE_URL = PG_URL
    from app.services import pg
    from app.services.trip_repo_pg import PostgresTripRepo
    pg.reset_pool(); pg.ensure_schema()
    with pg.connection() as conn:
        conn.execute("truncate trips")
    return PostgresTripRepo()


@pytest.fixture(params=["fs", "pg"])
def repo(request, tmp_path):
    if request.param == "fs":
        return FilesystemTripRepo(tmp_path)
    if not PG_URL:
        pytest.skip("set TEST_DATABASE_URL for the postgres backend")
    return _make_pg_repo()


def test_contract_roundtrip(repo):
    assert repo.get("x") is None and repo.exists("x") is False
    repo.save("x", _trip("x"))
    assert repo.exists("x") and repo.get("x").park == "balsam-lake"
    repo.set_routes("x", [{"leg": 1}])
    assert repo.get_routes("x") == [{"leg": 1}]
    repo.save("a", _trip("a"))
    assert set(repo.list_slugs()) >= {"a", "x"}
    repo.delete("x")
    assert repo.exists("x") is False
