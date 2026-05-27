import importlib
import app.config as config


def test_auth_defaults_off(monkeypatch):
    for k in ("AUTH_ENABLED", "SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_JWT_SECRET"):
        monkeypatch.delenv(k, raising=False)
    importlib.reload(config)
    assert config.AUTH_ENABLED is False
    assert config.SUPABASE_URL is None


def test_auth_enabled_from_env(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    importlib.reload(config)
    assert config.AUTH_ENABLED is True
    assert config.SUPABASE_URL == "https://x.supabase.co"


def teardown_module(module):
    importlib.reload(config)
