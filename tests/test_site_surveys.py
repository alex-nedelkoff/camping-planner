import json

import pytest

from app import config
from app.services import site_surveys


@pytest.fixture
def surveys_dir(tmp_path, monkeypatch):
    d = tmp_path / "site_surveys"
    d.mkdir()
    monkeypatch.setattr(config, "SITE_SURVEYS_DIR", d)
    monkeypatch.setattr(site_surveys, "SITE_SURVEYS_DIR", d)
    return d


def _write(d, slug, park_name=None, site_count=1, sites=None):
    payload = {
        "park_slug": slug,
        "park_name": park_name or slug,
        "pulled_on": "2026-05-24",
        "site_count": site_count,
        "sites": sites if sites is not None else [
            {"name": "1", "campground": "A", "equipment_bucket": "Tent only",
             "description": "", "max_capacity": 6, "attributes": {}, "photos": []}
        ],
    }
    (d / f"{slug}.json").write_text(json.dumps(payload))


def test_list_surveys_returns_summaries(surveys_dir):
    _write(surveys_dir, "balsam-lake", park_name="Balsam Lake", site_count=3)
    out = site_surveys.list_surveys()
    assert len(out) == 1
    assert out[0]["park_slug"] == "balsam-lake"
    assert out[0]["site_count"] == 3
    assert out[0]["pulled_on"] == "2026-05-24"


def test_list_surveys_sorted_by_name(surveys_dir):
    _write(surveys_dir, "z-park", park_name="Zed")
    _write(surveys_dir, "a-park", park_name="Algonquin")
    out = site_surveys.list_surveys()
    assert [e["park_name"] for e in out] == ["Algonquin", "Zed"]


def test_list_surveys_empty_when_no_dir(tmp_path, monkeypatch):
    missing = tmp_path / "nope"
    monkeypatch.setattr(site_surveys, "SITE_SURVEYS_DIR", missing)
    assert site_surveys.list_surveys() == []


def test_load_survey_returns_full(surveys_dir):
    _write(surveys_dir, "balsam-lake")
    s = site_surveys.load_survey("balsam-lake")
    assert s["park_slug"] == "balsam-lake"
    assert "sites" in s


def test_load_survey_missing_returns_none(surveys_dir):
    assert site_surveys.load_survey("nope") is None


def test_derive_filters():
    sites = [
        {"campground": "A", "equipment_bucket": "Tent only",
         "attributes": {"Privacy": "Good", "Site Length (m)": 12}},
        {"campground": "B", "equipment_bucket": "RV / big rig",
         "attributes": {"Privacy": "Poor", "Site Length (m)": 24}},
        {"campground": "A", "equipment_bucket": "Tent only", "attributes": {}},
    ]
    f = site_surveys.derive_filters(sites)
    assert f["campgrounds"] == ["A", "B"]
    assert f["privacy"] == ["Good", "Poor"]
    assert f["has_unrated"] is True
    assert f["equipment"] == ["Tent only", "RV / big rig"]
    assert f["len_min"] == 12 and f["len_max"] == 24
