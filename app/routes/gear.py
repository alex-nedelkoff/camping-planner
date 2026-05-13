"""Gear row CRUD endpoints, member-gated."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.services import broadcast, gear_repo
from app.services.identity import require_trip_member

router = APIRouter(prefix="/api/trips/{slug}/gear", tags=["gear"])


class GearIn(BaseModel):
    category: str
    item: str
    quantity: str | None = ""
    assigned_to: str | None = ""
    notes: str | None = ""
    sort_order: float


class GearPatch(BaseModel):
    expected_updated_at: str
    category: str | None = None
    item: str | None = None
    quantity: str | None = None
    assigned_to: str | None = None
    notes: str | None = None
    sort_order: float | None = None


@router.get("")
async def list_gear(slug: str, request: Request):
    require_trip_member(request, slug)
    return {"rows": gear_repo.list_for_trip(slug)}


@router.post("")
async def create_gear(slug: str, body: GearIn, request: Request):
    user = require_trip_member(request, slug)
    row = gear_repo.insert(
        trip_slug=slug,
        category=body.category, item=body.item, quantity=body.quantity,
        assigned_to=body.assigned_to, notes=body.notes,
        sort_order=body.sort_order, user_id=user["id"],
    )
    await broadcast.default_bus.publish(slug, {"type": "gear.upsert", "row": row})
    return {"row": row}


@router.put("/{row_id}")
async def update_gear(slug: str, row_id: int,
                      body: GearPatch, request: Request):
    user = require_trip_member(request, slug)
    fields = {k: v for k, v in body.model_dump().items()
              if k != "expected_updated_at" and v is not None}
    try:
        row = gear_repo.update(
            row_id,
            expected_updated_at=body.expected_updated_at,
            user_id=user["id"], **fields,
        )
    except gear_repo.Conflict as e:
        # Flatter shape than HTTPException(detail=...) — clients read
        # response.current directly, not response.detail.current.
        return JSONResponse(status_code=409, content={"current": e.current})
    await broadcast.default_bus.publish(slug, {"type": "gear.upsert", "row": row})
    return {"row": row}


@router.delete("/{row_id}")
async def delete_gear(slug: str, row_id: int, request: Request):
    require_trip_member(request, slug)
    gear_repo.delete(row_id)
    await broadcast.default_bus.publish(slug, {"type": "gear.delete", "id": row_id})
    return {"ok": True}
