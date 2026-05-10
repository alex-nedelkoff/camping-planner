"""Tests for gpx_library.py."""
from pathlib import Path

from gpx_library import (
    _segment_track,
    _extract_connectors,
    find_connector,
)


def _two_lakes():
    """Two adjacent square lakes for synthetic testing."""
    return [
        {
            "name": "Alpha Lake",
            "polygon": [
                [46.00, -81.02], [46.00, -81.01],
                [46.01, -81.01], [46.01, -81.02],
                [46.00, -81.02],
            ],
            "centroid": [46.005, -81.015],
        },
        {
            "name": "Beta Lake",
            "polygon": [
                [46.00, -81.00], [46.00, -80.99],
                [46.01, -80.99], [46.01, -81.00],
                [46.00, -81.00],
            ],
            "centroid": [46.005, -80.995],
        },
    ]


def test_segment_track_classifies_in_lake_vs_on_land():
    lakes = _two_lakes()
    # Trace: start in Alpha, paddle east, cross land, land in Beta.
    points = [
        [46.005, -81.018],  # in Alpha
        [46.005, -81.012],  # in Alpha (closer to east edge)
        [46.005, -81.005],  # on land (between lakes)
        [46.005, -80.995],  # in Beta
        [46.005, -80.992],  # in Beta
    ]
    runs = _segment_track(points, lakes)
    states = [r["state"] for r in runs]
    assert states == ["Alpha Lake", None, "Beta Lake"]


def test_extract_connectors_emits_lake_pair_with_split_geometry():
    lakes = _two_lakes()
    points = [
        [46.005, -81.018],
        [46.005, -81.012],
        [46.005, -81.005],
        [46.005, -80.995],
        [46.005, -80.992],
    ]
    runs = _segment_track(points, lakes)
    connectors = _extract_connectors(runs)
    assert len(connectors) == 1
    c = connectors[0]
    assert c["lake_a"] == "Alpha Lake"
    assert c["lake_b"] == "Beta Lake"
    assert len(c["approach"]) == 2
    assert len(c["portage"]) == 1
    assert len(c["departure"]) == 2
    assert c["portage_km"] >= 0


def test_extract_connectors_skips_same_lake_land_runs():
    """A land run with the SAME lake on both sides (peninsula crossing) is dropped."""
    lakes = _two_lakes()
    points = [
        [46.005, -81.018],
        [46.005, -81.012],
        [46.0, -81.05],     # outside Alpha (crossing land near it but no Beta on far side)
        [46.005, -81.012],  # back in Alpha
        [46.005, -81.018],
    ]
    runs = _segment_track(points, lakes)
    assert _extract_connectors(runs) == []


def test_find_connector_picks_shortest_portage_and_orients_correctly():
    lib = {
        "connectors": [
            {
                "lake_a": "Alpha Lake", "lake_b": "Beta Lake",
                "approach": [[1, 1]], "portage": [[2, 2], [3, 3]],
                "departure": [[4, 4]],
                "approach_km": 0.1, "portage_km": 0.5, "departure_km": 0.1,
            },
            {
                "lake_a": "Beta Lake", "lake_b": "Alpha Lake",
                "approach": [[10, 10]], "portage": [[20, 20]],
                "departure": [[30, 30]],
                "approach_km": 0.2, "portage_km": 0.3, "departure_km": 0.2,
            },
        ],
    }
    # Request Alpha->Beta. The shortest portage is the second entry but it's
    # oriented Beta->Alpha, so it should be reversed to read Alpha->Beta.
    c = find_connector("Alpha Lake", "Beta Lake", lib)
    assert c["lake_a"] == "Alpha Lake"
    assert c["lake_b"] == "Beta Lake"
    assert c["portage_km"] == 0.3
    # When reversed, what WAS the departure becomes the approach.
    assert c["approach"] == [[30, 30]]
    assert c["departure"] == [[10, 10]]


def test_validate_connector_rejects_noise_and_accepts_real():
    from gpx_library import _validate_connector
    osm_index = {
        frozenset({"Alpha Lake", "Beta Lake"}): [
            {"length_km": 0.4},  # OSM has a real ~400m portage between them
        ],
    }

    # Real-looking portage: ~400m, plenty of points, OSM corroborates.
    real = {
        "lake_a": "Alpha Lake", "lake_b": "Beta Lake",
        "portage_km": 0.39, "portage": [[1, 1]] * 12,
    }
    trusted, _ = _validate_connector(real, osm_index)
    assert trusted is True

    # Too-short portage: <50m, segmentation noise.
    short = {**real, "portage_km": 0.018, "portage": [[1, 1]] * 2}
    trusted, reason = _validate_connector(short, osm_index)
    assert trusted is False
    assert "short" in reason.lower()

    # Zero portage_km: GPS skipped land entirely.
    zero = {**real, "portage_km": 0.0, "portage": [[1, 1]]}
    trusted, _ = _validate_connector(zero, osm_index)
    assert trusted is False

    # OSM doesn't know this lake-pair: reject.
    novel = {
        "lake_a": "Gamma Lake", "lake_b": "Delta Lake",
        "portage_km": 0.4, "portage": [[1, 1]] * 12,
    }
    trusted, reason = _validate_connector(novel, osm_index)
    assert trusted is False
    assert "no osm portage" in reason.lower()

    # Length way off from OSM: reject.
    way_off = {**real, "portage_km": 2.5}  # OSM says 0.4, this says 2.5 (6x ratio)
    trusted, reason = _validate_connector(way_off, osm_index)
    assert trusted is False
    assert "length" in reason.lower()
