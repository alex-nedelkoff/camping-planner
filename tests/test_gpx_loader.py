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
