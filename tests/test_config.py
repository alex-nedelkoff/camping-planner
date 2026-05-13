"""Config env overrides."""

import importlib

import pytest


def test_data_dir_env_overrides_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import app.config as cfg
    importlib.reload(cfg)
    assert cfg.TRIPS_DIR == tmp_path / "trips"
    assert cfg.DATABASE_PATH == tmp_path / "camping.sqlite3"


def test_no_data_dir_falls_back_to_repo(monkeypatch):
    monkeypatch.delenv("DATA_DIR", raising=False)
    import app.config as cfg
    importlib.reload(cfg)
    assert cfg.TRIPS_DIR.name == "trips"
    assert cfg.TRIPS_DIR.parent.name == "camping-planner" or \
           cfg.TRIPS_DIR.parent.name.startswith("collab-editing")  # worktree
