"""Tests for Pydantic models for trip.json v1."""

import pytest
from pydantic import ValidationError

from app.models_trip import Trip, TripDates, Night


def test_trip_minimal_validates():
    t = Trip(
        schema_version=1,
        name="killarney-2026-05",
        park="killarney",
        dates=TripDates(start="2026-05-15", end="2026-05-18"),
        participants=["Alex"],
        access_point="George Lake",
        nights=[],
        itinerary=[],
        gear=[],
        food=[],
        costs=[],
        )
    assert t.schema_version == 1
    assert t.dates.start.isoformat() == "2026-05-15"


def test_trip_rejects_wrong_schema_version():
    with pytest.raises(ValidationError):
        Trip(schema_version=99, name="x", park="y",
             dates=TripDates(start="2026-01-01", end="2026-01-02"),
             participants=[], access_point="", nights=[],
             itinerary=[], gear=[],
             food=[], costs=[], )


def test_night_optional_gps():
    n = Night(date="2026-05-15", site="61", location="OSA Lake")
    assert n.gps is None
    n2 = Night(date="2026-05-15", site="61", location="OSA",
               gps=[46.04, -81.50])
    assert n2.gps == [46.04, -81.50]
