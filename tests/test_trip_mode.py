import pytest
from pydantic import ValidationError

from app.models_trip import Trip, TripDates


def _base(**kw):
    data = dict(schema_version=1, name="t", park="balsam-lake",
                dates=TripDates(start="2026-05-30", end="2026-05-31"))
    data.update(kw)
    return Trip(**data)


def test_mode_defaults_to_paddle():
    assert _base().mode == "paddle"


def test_mode_accepts_car_camping():
    assert _base(mode="car_camping").mode == "car_camping"


def test_mode_rejects_unknown():
    with pytest.raises(ValidationError):
        _base(mode="spaceship")
