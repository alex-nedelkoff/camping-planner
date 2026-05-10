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


class SaveSectionRequest(BaseModel):
    markdown: str


class SectionResponse(BaseModel):
    ok: bool = True
    section: str
    markdown: str


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
    kind: str = "html"
    payload: dict | None = None


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


class FoodIn(BaseModel):
    name: str = Field(min_length=1)
    category: str
    kcal_per_serving: int = Field(ge=0)
    serving_size: str = Field(min_length=1)
    url: str | None = None


class FoodOut(FoodIn):
    id: str


class FoodsCatalogResponse(BaseModel):
    ok: bool = True
    categories: list[str]
    foods: list[FoodOut]


class FoodCreatedResponse(BaseModel):
    ok: bool = True
    id: str


class FoodReferencesResponse(BaseModel):
    ok: bool = True
    references: list[str]


class MealItem(BaseModel):
    food_id: str
    servings: int = Field(ge=0)
    who: str = ""
    note: str = ""


class MealEntry(BaseModel):
    meal: str
    items: list[MealItem] = Field(default_factory=list)


class DayPlan(BaseModel):
    date: str
    label: str = ""
    meals: list[MealEntry] = Field(default_factory=list)


class CalorieTarget(BaseModel):
    activity_level: str
    kcal_per_person_per_day: int = Field(ge=0)


class MealPlanIn(BaseModel):
    calorie_target: CalorieTarget
    days: list[DayPlan] = Field(default_factory=list)


class MealPlanOut(BaseModel):
    ok: bool = True
    plan: dict
    totals: dict


class GearItemIn(BaseModel):
    name: str = Field(min_length=1)
    category: str
    weight_g: int | None = Field(default=None, ge=0)


class GearItemOut(GearItemIn):
    id: str


class GearCatalogResponse(BaseModel):
    ok: bool = True
    categories: list[str]
    items: list[GearItemOut]


class GearItemCreatedResponse(BaseModel):
    ok: bool = True
    id: str


class GearReferencesResponse(BaseModel):
    ok: bool = True
    references: list[str]


class CategoryRequest(BaseModel):
    name: str = Field(min_length=1, max_length=40)


class CategoryRenameRequest(BaseModel):
    new_name: str = Field(min_length=1, max_length=40)
