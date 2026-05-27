import importlib
import app.config as config


def test_storage_backend_defaults_to_filesystem(monkeypatch):
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    importlib.reload(config)  # re-evaluate os.environ at module level
    assert config.STORAGE_BACKEND == "filesystem"
    assert config.DATABASE_URL is None


def test_storage_backend_from_env(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x/y")
    importlib.reload(config)  # re-evaluate os.environ at module level
    assert config.STORAGE_BACKEND == "postgres"
    assert config.DATABASE_URL == "postgresql://x/y"


def test_empty_database_url_normalizes_to_none(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    importlib.reload(config)
    assert config.DATABASE_URL is None


def teardown_module(module):
    importlib.reload(config)  # restore defaults for other tests
