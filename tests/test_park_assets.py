import app.services.park_assets as pa


def _mkparkdir(tmp_path, slug, files):
    d = tmp_path / slug
    d.mkdir(parents=True)
    for f in files:
        (d / f).write_bytes(b"\x89PNG\r\n")  # dummy content; only presence matters
    return d


def test_hero_image_per_park(tmp_path, monkeypatch):
    monkeypatch.setattr(pa, "PARKS_IMG_DIR", tmp_path)
    _mkparkdir(tmp_path, "balsam-lake", ["hero.jpg"])
    assert pa.hero_image("balsam-lake") == "/static/img/parks/balsam-lake/hero.jpg"


def test_hero_image_falls_back_to_default(tmp_path, monkeypatch):
    monkeypatch.setattr(pa, "PARKS_IMG_DIR", tmp_path)
    assert pa.hero_image("no-such-park") == pa.DEFAULT_HERO


def test_park_maps_lists_existing_campground_first(tmp_path, monkeypatch):
    monkeypatch.setattr(pa, "PARKS_IMG_DIR", tmp_path)
    _mkparkdir(tmp_path, "balsam-lake", ["park-map.png", "campground-map.png"])
    maps = pa.park_maps("balsam-lake")
    assert [m["title"] for m in maps] == ["Campground map", "Park map"]
    assert maps[0]["url"] == "/static/img/parks/balsam-lake/campground-map.png"


def test_park_maps_empty_when_none(tmp_path, monkeypatch):
    monkeypatch.setattr(pa, "PARKS_IMG_DIR", tmp_path)
    assert pa.park_maps("no-such-park") == []
