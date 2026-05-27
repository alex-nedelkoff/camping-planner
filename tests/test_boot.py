import app.config as config


def test_filesystem_boot_uses_sqlite(monkeypatch):
    monkeypatch.setattr(config, "STORAGE_BACKEND", "filesystem")
    from app import main
    main.init_storage()  # must not raise without a DATABASE_URL


def test_postgres_boot_requires_pool(monkeypatch):
    monkeypatch.setattr(config, "STORAGE_BACKEND", "postgres")
    monkeypatch.setattr(config, "DATABASE_URL", None)
    from app import main
    from app.services import pg
    pg.reset_pool()
    import pytest
    with pytest.raises(RuntimeError):
        main.init_storage()
