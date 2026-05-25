import json

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.services import site_surveys


@pytest.fixture
def client(tmp_path, monkeypatch):
    d = tmp_path / "site_surveys"
    d.mkdir()
    (d / "balsam-lake.json").write_text(json.dumps({
        "park_slug": "balsam-lake",
        "park_name": "Balsam Lake",
        "pulled_on": "2026-05-24",
        "site_count": 1,
        "sites": [{
            "name": "312", "campground": "Sites #300-360",
            "equipment_bucket": "Tent only", "description": "lakeside",
            "max_capacity": 6,
            "attributes": {"Privacy": "Good", "Site Length (m)": 15},
            "photos": [],
        }],
    }))
    monkeypatch.setattr(config, "SITE_SURVEYS_DIR", d)
    monkeypatch.setattr(site_surveys, "SITE_SURVEYS_DIR", d)
    return TestClient(app)


def test_sites_index_lists_park(client):
    r = client.get("/sites")
    assert r.status_code == 200
    assert "Balsam Lake" in r.text
    assert "/sites/balsam-lake" in r.text


def test_sites_park_renders_sites_and_filters(client):
    r = client.get("/sites/balsam-lake")
    assert r.status_code == 200
    assert "312" in r.text
    assert "Campground" in r.text
    assert 'class="f-priv"' in r.text


def test_sites_park_unknown_returns_404(client):
    r = client.get("/sites/does-not-exist")
    assert r.status_code == 404


def test_home_page_links_to_sites(client):
    r = client.get("/")
    assert r.status_code == 200
    assert 'href="/sites"' in r.text
