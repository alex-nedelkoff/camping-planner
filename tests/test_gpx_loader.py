"""Tests for gpx_loader.py."""
from pathlib import Path

import pytest

from gpx_loader import load_campsites


CAMPSITES_GPX = """<?xml version="1.0" encoding="utf-8"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
<wpt lat="46.02358" lon="-81.41387">
  <name>1</name>
  <desc>Killarney 1, Open-Potential</desc>
</wpt>
<wpt lat="46.05199" lon="-81.36224">
  <name>61</name>
  <desc>Killarney 61, Open-Potential, Avg User Rating: 4 out of 5</desc>
</wpt>
</gpx>
"""


def test_load_campsites_parses_name_lat_lon_desc(tmp_path):
    gpx = tmp_path / "campsites.gpx"
    gpx.write_text(CAMPSITES_GPX)
    sites = load_campsites(gpx)
    assert len(sites) == 2
    assert sites[0] == {
        "name": "1",
        "lat": 46.02358,
        "lon": -81.41387,
        "desc": "Killarney 1, Open-Potential",
    }
    assert sites[1]["name"] == "61"
    assert sites[1]["lat"] == 46.05199


from gpx_loader import load_portages


PORTAGES_GPX = """<?xml version="1.0" encoding="utf-8"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
<wpt lat="46.03524" lon="-81.38126">
  <name>42056</name>
  <desc>Killarney Portage 42056, ~58 meters (11 rods)</desc>
</wpt>
<wpt lat="46.03535" lon="-81.38053">
  <name>42056</name>
  <desc>Killarney Portage 42056, ~58 meters (11 rods)</desc>
</wpt>
<wpt lat="46.10000" lon="-81.50000">
  <name>99999</name>
  <desc>Orphan, no partner</desc>
</wpt>
</gpx>
"""

PORTAGES_GPX_NO_METERS = """<?xml version="1.0" encoding="utf-8"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
<wpt lat="46.0000" lon="-81.0000">
  <name>42100</name>
  <desc>Killarney Portage 42100 (length unknown)</desc>
</wpt>
<wpt lat="46.0010" lon="-81.0010">
  <name>42100</name>
  <desc>Killarney Portage 42100 (length unknown)</desc>
</wpt>
</gpx>
"""


def test_load_portages_pairs_two_waypoints_per_id(tmp_path):
    gpx = tmp_path / "portages.gpx"
    gpx.write_text(PORTAGES_GPX)
    portages = load_portages(gpx)
    # Orphan 99999 is dropped; only 42056 returned.
    assert len(portages) == 1
    p = portages[0]
    assert p["name"] == "42056"
    assert p["endpoints"] == [[46.03524, -81.38126], [46.03535, -81.38053]]
    # `line` mirrors endpoints (straight line between them).
    assert p["line"] == p["endpoints"]
    assert p["source"] == "gpx"


def test_load_portages_drops_orphans_with_warning(tmp_path, caplog):
    import logging
    gpx = tmp_path / "portages.gpx"
    gpx.write_text(PORTAGES_GPX)
    with caplog.at_level(logging.WARNING):
        portages = load_portages(gpx)
    assert all(p["name"] != "99999" for p in portages)
    assert any("99999" in r.message for r in caplog.records)


def test_load_portages_parses_length_from_description(tmp_path):
    gpx = tmp_path / "portages.gpx"
    gpx.write_text(PORTAGES_GPX)
    portages = load_portages(gpx)
    # "~58 meters" → 0.058 km.
    assert abs(portages[0]["length_km"] - 0.058) < 1e-6


def test_load_portages_falls_back_to_haversine_when_no_meters(tmp_path):
    gpx = tmp_path / "portages.gpx"
    gpx.write_text(PORTAGES_GPX_NO_METERS)
    portages = load_portages(gpx)
    assert len(portages) == 1
    # Haversine of [46.0, -81.0] to [46.001, -81.001]:
    # ~0.137 km (1 deg lat ≈ 111 km, so 0.001 deg lat ≈ 0.111 km;
    # combined ~ sqrt(0.111^2 + 0.0772^2) ≈ 0.135-0.140).
    assert 0.10 <= portages[0]["length_km"] <= 0.20
