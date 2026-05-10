"""Foods catalog HTTP routes."""

from fastapi import APIRouter, HTTPException, Query

from app.models import (
    FoodCreatedResponse,
    FoodIn,
    FoodReferencesResponse,
    FoodsCatalogResponse,
    OkResponse,
)
from app.services import foods as foods_svc

router = APIRouter(prefix="/api/foods")


@router.get("", response_model=FoodsCatalogResponse)
def get_catalog():
    cat = foods_svc.load_catalog()
    return FoodsCatalogResponse(categories=cat["categories"], foods=cat["foods"])


@router.post("", response_model=FoodCreatedResponse)
def create_food(food: FoodIn):
    try:
        new_id = foods_svc.upsert(food.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"ok": False, "error": str(exc)})
    return FoodCreatedResponse(id=new_id)


@router.put("/{food_id}", response_model=OkResponse)
def update_food(food_id: str, food: FoodIn):
    try:
        foods_svc.upsert({"id": food_id, **food.model_dump()})
    except KeyError:
        raise HTTPException(status_code=404, detail={"ok": False, "error": "food not found"})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"ok": False, "error": str(exc)})
    return OkResponse()


@router.delete("/{food_id}", response_model=OkResponse)
def delete_food(food_id: str, force: bool = Query(default=False)):
    if foods_svc.get(food_id) is None:
        raise HTTPException(status_code=404, detail={"ok": False, "error": "food not found"})
    if not force:
        refs = foods_svc.find_references(food_id)
        if refs:
            raise HTTPException(
                status_code=409,
                detail={"ok": False, "error": "food is referenced", "references": refs},
            )
    foods_svc.delete(food_id)
    return OkResponse()


@router.get("/refs/{food_id}", response_model=FoodReferencesResponse)
def food_references(food_id: str):
    return FoodReferencesResponse(references=foods_svc.find_references(food_id))
