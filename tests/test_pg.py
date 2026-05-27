import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="set TEST_DATABASE_URL to run Postgres-backed tests",
)


def test_pool_and_schema(monkeypatch):
    import app.config as config
    monkeypatch.setattr(config, "DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    from app.services import pg
    pg.reset_pool()
    pg.ensure_schema()
    with pg.connection() as conn:
        row = conn.execute("select 1 as n").fetchone()
    assert row[0] == 1
