from app.services import getting_there as gt


def test_build_assembles_drive_site_and_map(monkeypatch):
    monkeypatch.setattr(gt.parks_svc, "load_park_info", lambda slug: {
        "name": "Balsam Lake", "driveFromAjax": "1.25 hrs",
        "campgroundMapUrl": "https://example.com/map.pdf",
    })
    monkeypatch.setattr(gt.site_surveys, "load_survey", lambda slug: {
        "park_slug": slug, "sites": [{"name": "123", "campground": "Maple"}],
    })
    monkeypatch.setattr(gt.weather, "PARK_COORDS", {"balsam-lake": (44.58, -78.85)})

    ctx = gt.build("balsam-lake", booked_site="Site 123")
    assert ctx["park_name"] == "Balsam Lake"
    assert ctx["drive_label"] == "1.25 hrs"
    assert ctx["map_url"] == "https://example.com/map.pdf"
    assert "44.58" in ctx["directions_url"] and "-78.85" in ctx["directions_url"]
    assert ctx["booked_site"]["campground"] == "Maple"


def test_build_degrades_when_no_data(monkeypatch):
    monkeypatch.setattr(gt.parks_svc, "load_park_info", lambda slug: {})
    monkeypatch.setattr(gt.site_surveys, "load_survey", lambda slug: None)
    monkeypatch.setattr(gt.weather, "PARK_COORDS", {})

    ctx = gt.build("unknown-park", booked_site="")
    assert ctx["booked_site"] is None
    assert ctx["drive_label"] is None
    assert ctx["map_url"] is None
    assert ctx["directions_url"] is None


def test_build_includes_home_and_park_coords(monkeypatch):
    monkeypatch.setattr(gt.parks_svc, "load_park_info", lambda slug: {"name": "Balsam Lake"})
    monkeypatch.setattr(gt.site_surveys, "load_survey", lambda slug: None)
    monkeypatch.setattr(gt.weather, "PARK_COORDS", {"balsam-lake": (44.58, -78.85)})
    monkeypatch.setattr(gt.config, "HOME_COORDS", (43.851, -79.020))
    monkeypatch.setattr(gt.config, "HOME_LABEL", "Ajax")

    ctx = gt.build("balsam-lake", booked_site="")
    assert ctx["home_coords"] == (43.851, -79.020)
    assert ctx["home_label"] == "Ajax"
    assert ctx["park_coords"] == (44.58, -78.85)


def test_build_park_coords_none_when_unknown(monkeypatch):
    monkeypatch.setattr(gt.parks_svc, "load_park_info", lambda slug: {})
    monkeypatch.setattr(gt.site_surveys, "load_survey", lambda slug: None)
    monkeypatch.setattr(gt.weather, "PARK_COORDS", {})
    ctx = gt.build("unknown", booked_site="")
    assert ctx["park_coords"] is None
