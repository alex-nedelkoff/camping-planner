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


class GearItem(BaseModel):
    item: str
    who: str = ""
    notes: str = ""


class PersonalGear(BaseModel):
    person: str
    items: list[GearItem] = Field(default_factory=list)


class GearSection(BaseModel):
    shared: list[GearItem] = Field(default_factory=list)
    personal: list[PersonalGear] = Field(default_factory=list)


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


class PackingItem(BaseModel):
    label: str
    checked: bool = False


class PackingCategory(BaseModel):
    category: str
    items: list[PackingItem] = Field(default_factory=list)


class ItineraryDay(BaseModel):
    date: date
    label: str = ""
    notes: str = ""


class Trip(BaseModel):
    schema_version: Literal[1]
    name: str
    park: str
    dates: TripDates
    participants: list[str] = Field(default_factory=list)
    access_point: str = ""
    nights: list[Night] = Field(default_factory=list)
    itinerary: list[ItineraryDay] = Field(default_factory=list)
    gear: GearSection = Field(default_factory=GearSection)
    food: list[FoodSlot] = Field(default_factory=list)
    costs: list[CostRow] = Field(default_factory=list)
    packing: list[PackingCategory] = Field(default_factory=list)
