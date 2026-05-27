import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="set TEST_DATABASE_URL to run migration round-trip",
)


def test_migrate_then_export_roundtrip(tmp_path, monkeypatch):
    import app.config as config
    monkeypatch.setattr(config, "DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setattr(config, "TRIPS_DIR", tmp_path)
    # seed one filesystem trip
    d = tmp_path / "balsam-lake-2026-05"; d.mkdir()
    (d / "trip.json").write_text('{"schema_version":1,"name":"balsam-lake-2026-05",'
        '"park":"balsam-lake","mode":"car_camping",'
        '"dates":{"start":"2026-05-30","end":"2026-05-31"}}')
    from app.services import pg
    pg.reset_pool(); pg.ensure_schema()
    with pg.connection() as conn:
        conn.execute("truncate trips")
    import scripts.migrate_to_supabase as mig
    mig.run(tmp_path)
    out = tmp_path / "out"; out.mkdir()
    import scripts.export_trips as exp
    exp.run(out)
    assert (out / "balsam-lake-2026-05" / "trip.json").exists()
