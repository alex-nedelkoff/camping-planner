"""Pydantic request/response schemas for the API."""

from datetime import date

from pydantic import BaseModel, Field


class NewTripRequest(BaseModel):
    park: str = Field(min_length=1)
    start: date
    end: date
    participants: list[str] = Field(default_factory=list)


class SaveGearRequest(BaseModel):
    rows: list[list[str]]


class OkResponse(BaseModel):
    ok: bool = True
    message: str | None = None


class NewTripResponse(BaseModel):
    ok: bool = True
    trip_dir: str


class TripSection(BaseModel):
    id: str
    title: str
    html: str
    editable: bool


class TripPayloadResponse(BaseModel):
    ok: bool = True
    slug: str
    park_name: str
    frontmatter: dict
    header_html: str
    sections: list[TripSection]


class TripListItem(BaseModel):
    name: str
    park_name: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    participant_count: int = 0
    days_label: str | None = None
    bucket: str
    error: str | None = None


class TripListResponse(BaseModel):
    ok: bool = True
    trips: list[TripListItem]


class CampgroundAvailability(BaseModel):
    available: int
    total: int


class AvailabilityResponse(BaseModel):
    ok: bool = True
    park_name: str | None = None
    total_available: int = 0
    campgrounds: dict[str, CampgroundAvailability] = Field(default_factory=dict)
    cached: bool = False


class ChecklistGetResponse(BaseModel):
    ok: bool = True
    state: dict[str, bool]


class ChecklistSetRequest(BaseModel):
    key: str = Field(min_length=1)
    checked: bool


class WhoamiResponse(BaseModel):
    user: str


class WhoamiSetRequest(BaseModel):
    user: str = Field(min_length=1, max_length=40)
