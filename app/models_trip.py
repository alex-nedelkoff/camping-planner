"""Pydantic models for the trip.json schema (v1)."""

from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field


SCHEMA_VERSION = 1


class TripDates(BaseModel):
    start: date
    end: date


class Night(BaseModel):
    date: date
    site: str = ""
    location: str = ""
    gps: Optional[list[float]] = None


class TripItem(BaseModel):
    """Unified gear+packing item.

    bringers: list of participant names who are bringing/packing it.
    shared:   item is shared/community gear (a separate flag, independent of
              who's bringing it). Canoe is shared (one bringer). Headlamp
              is not shared (each person packs their own; bringers has both).
    A checkbox in the UI under attendee X = X in bringers. A checkbox in the
    Shared column = shared=True.
    """
    item: str
    category: str = ""
    notes: str = ""
    bringers: list[str] = Field(default_factory=list)
    shared: bool = False


class FoodItem(BaseModel):
    name: str
    who: str = ""


class FoodSlot(BaseModel):
    slot: str
    label: str
    items: list[FoodItem] = Field(default_factory=list)
    notes: str = ""


class CostRow(BaseModel):
    item: str
    who_paid: str = ""
    amount: Optional[float] = None
    currency: str = "CAD"


class ItineraryDay(BaseModel):
    date: date
    label: str = ""
    notes: str = ""


class Trip(BaseModel):
    schema_version: Literal[1]
    name: str
    park: str
    mode: Literal["paddle", "car_camping"] = "paddle"
    dates: TripDates
    participants: list[str] = Field(default_factory=list)
    access_point: str = ""
    nights: list[Night] = Field(default_factory=list)
    itinerary: list[ItineraryDay] = Field(default_factory=list)
    gear: list[TripItem] = Field(default_factory=list)
    food: list[FoodSlot] = Field(default_factory=list)
    costs: list[CostRow] = Field(default_factory=list)
