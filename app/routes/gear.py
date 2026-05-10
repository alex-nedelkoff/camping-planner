"""Gear catalog HTTP routes."""

from fastapi import APIRouter, HTTPException, Query

from app.models import (
    CategoryRenameRequest,
    CategoryRequest,
    GearCatalogResponse,
    GearItemCreatedResponse,
    GearItemIn,
    GearPlanIn,
    GearPlanOut,
    GearReferencesResponse,
    OkResponse,
)
from app.services import gear as gear_svc

router = APIRouter(prefix="/api/gear")


@router.get("", response_model=GearCatalogResponse)
def get_catalog():
    cat = gear_svc.load_catalog()
    return GearCatalogResponse(categories=cat["categories"], items=cat["items"])


@router.post("", response_model=GearItemCreatedResponse)
def create_item(item: GearItemIn):
    try:
        new_id = gear_svc.upsert(item.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"ok": False, "error": str(exc)})
    return GearItemCreatedResponse(id=new_id)


# More-specific paths first so they don't get shadowed by /{item_id}.
@router.get("/refs/{item_id}", response_model=GearReferencesResponse)
def item_references(item_id: str):
    return GearReferencesResponse(references=gear_svc.find_references(item_id))


@router.put("/{item_id}", response_model=OkResponse)
def update_item(item_id: str, item: GearItemIn):
    try:
        gear_svc.upsert({"id": item_id, **item.model_dump()})
    except KeyError:
        raise HTTPException(status_code=404, detail={"ok": False, "error": "item not found"})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"ok": False, "error": str(exc)})
    return OkResponse()


@router.delete("/{item_id}", response_model=OkResponse)
def delete_item(item_id: str, force: bool = Query(default=False)):
    if gear_svc.get(item_id) is None:
        raise HTTPException(status_code=404, detail={"ok": False, "error": "item not found"})
    if not force:
        refs = gear_svc.find_references(item_id)
        if refs:
            raise HTTPException(
                status_code=409,
                detail={"ok": False, "error": "item is referenced", "references": refs},
            )
    gear_svc.delete(item_id)
    return OkResponse()


categories_router = APIRouter(prefix="/api/gear/categories")


@categories_router.post("", response_model=OkResponse)
def add_category(body: CategoryRequest):
    try:
        gear_svc.add_category(body.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"ok": False, "error": str(exc)})
    return OkResponse()


@categories_router.put("/{old_name}", response_model=OkResponse)
def rename_category(old_name: str, body: CategoryRenameRequest):
    try:
        gear_svc.rename_category(old_name, body.new_name)
    except KeyError:
        raise HTTPException(status_code=404, detail={"ok": False, "error": "category not found"})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"ok": False, "error": str(exc)})
    return OkResponse()


@categories_router.delete("/{name}", response_model=OkResponse)
def delete_category(name: str, force: bool = Query(default=False)):
    try:
        gear_svc.delete_category(name, force=force)
    except KeyError:
        raise HTTPException(status_code=404, detail={"ok": False, "error": "category not found"})
    except ValueError as exc:
        # Distinguish "in use" (409) from validation errors (400).
        if "in use" in str(exc):
            raise HTTPException(
                status_code=409, detail={"ok": False, "error": str(exc)},
            )
        raise HTTPException(status_code=400, detail={"ok": False, "error": str(exc)})
    return OkResponse()


trip_gear_router = APIRouter(prefix="/api/trip")


@trip_gear_router.get("/{slug}/gear-plan", response_model=GearPlanOut)
def get_gear_plan(slug: str):
    from app.services import gear_plan as gp_svc
    try:
        plan = gp_svc.load(slug)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail={"ok": False, "error": "trip not found"})
    catalog = gear_svc.load_catalog()
    totals = gp_svc.compute_totals(plan, catalog)
    return GearPlanOut(plan=plan, totals=totals)


@trip_gear_router.post("/{slug}/gear-plan", response_model=OkResponse)
def save_gear_plan(slug: str, body: GearPlanIn):
    from app.services import gear_plan as gp_svc
    try:
        catalog = gear_svc.load_catalog()
        gp_svc.save(slug, body.model_dump(), catalog=catalog)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail={"ok": False, "error": "trip not found"})
    return OkResponse()
