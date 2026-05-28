"""Cookbook routes — server-rendered list + detail + create/edit forms."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.deps import require_user
from app.services import identity, recipes
from app.templating import templates

router = APIRouter()


def _all_tags(rs: list[recipes.Recipe]) -> list[str]:
    seen: dict[str, int] = {}
    for r in rs:
        for t in r.tags:
            seen[t] = seen.get(t, 0) + 1
    return sorted(seen, key=lambda t: (-seen[t], t))


def _parse_ingredients(form_qty: list[str], form_unit: list[str],
                       form_name: list[str]) -> list[dict]:
    rows = []
    for q, u, n in zip(form_qty, form_unit, form_name):
        if (n or "").strip():
            rows.append({"qty": q, "unit": u, "name": n})
    return rows


async def _read_image(image: Optional[UploadFile]) -> tuple[Optional[bytes], Optional[str]]:
    if image is None or not image.filename:
        return None, None
    data = await image.read()
    if not data:
        return None, None
    if not (image.content_type or "").startswith("image/"):
        raise HTTPException(status_code=400, detail="attachment must be an image")
    if len(data) > recipes.MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="image too large (max 5 MB)")
    return data, image.content_type


def _nav(user) -> dict:
    return {"home_href": "/", "user_email": user.email, "back_href": "/recipes",
            "back_label": "Cookbook"}


# ---- list ------------------------------------------------------------------

@router.get("/recipes", response_class=HTMLResponse)
def recipes_index(request: Request,
                  style: Optional[str] = Query(None),
                  meal: Optional[str] = Query(None),
                  tag: Optional[str] = Query(None),
                  q: Optional[str] = Query(None),
                  user: identity.User = Depends(require_user)):
    all_recipes = recipes.list_recipes()
    filtered = recipes.list_recipes(style=style, meal=meal, tag=tag, q=q)
    return templates.TemplateResponse(request, "recipes_index.html", {
        "recipes": filtered,
        "filters": {"style": style, "meal": meal, "tag": tag, "q": q or ""},
        "styles": recipes.STYLES,
        "meals": recipes.MEALS,
        "all_tags": _all_tags(all_recipes),
        "current_user": user.id,
        "nav": {"home_href": "/", "user_email": user.email},
    })


# ---- create ----------------------------------------------------------------

@router.get("/recipes/new", response_class=HTMLResponse)
def new_form(request: Request, user: identity.User = Depends(require_user)):
    return templates.TemplateResponse(request, "recipe_form.html", {
        "recipe": None, "styles": recipes.STYLES, "meals": recipes.MEALS,
        "form_action": "/recipes", "form_title": "New recipe",
        "nav": _nav(user),
    })


@router.post("/recipes")
async def create(
    request: Request,
    name: str = Form(...),
    style: str = Form(...),
    meal: str = Form(...),
    servings: str = Form("1"),
    prep_minutes: str = Form(""),
    cook_minutes: str = Form(""),
    ing_qty: list[str] = Form(default=[]),
    ing_unit: list[str] = Form(default=[]),
    ing_name: list[str] = Form(default=[]),
    steps: str = Form(""),
    prep_at_home: str = Form(""),
    gear: str = Form(""),
    tags: str = Form(""),
    notes: str = Form(""),
    image: Optional[UploadFile] = File(None),
    user: identity.User = Depends(require_user),
):
    image_bytes, image_mime = await _read_image(image)
    try:
        rid = recipes.create(
            author=user.id, name=name, style=style, meal=meal, servings=servings,
            prep_minutes=prep_minutes, cook_minutes=cook_minutes,
            ingredients=_parse_ingredients(ing_qty, ing_unit, ing_name),
            steps=steps, prep_at_home=prep_at_home, gear=gear, tags=tags, notes=notes,
            image=image_bytes, image_mime=image_mime,
        )
    except recipes.RecipeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse(f"/recipes/{rid}", status_code=303)


# ---- detail ----------------------------------------------------------------

@router.get("/recipes/{rid}", response_class=HTMLResponse)
def detail(rid: str, request: Request, user: identity.User = Depends(require_user)):
    r = recipes.get(rid)
    if r is None:
        raise HTTPException(status_code=404, detail="recipe not found")
    return templates.TemplateResponse(request, "recipe_detail.html", {
        "r": r, "current_user": user.id, "nav": _nav(user),
    })


@router.get("/recipes/{rid}/image")
def image(rid: str, user: identity.User = Depends(require_user)):
    img = recipes.get_image(rid)
    if img is None:
        raise HTTPException(status_code=404, detail="no image")
    data, mime = img
    return Response(content=data, media_type=mime)


# ---- edit / update ---------------------------------------------------------

@router.get("/recipes/{rid}/edit", response_class=HTMLResponse)
def edit_form(rid: str, request: Request, user: identity.User = Depends(require_user)):
    r = recipes.get(rid)
    if r is None:
        raise HTTPException(status_code=404, detail="recipe not found")
    if r.author != user.id:
        raise HTTPException(status_code=403, detail="you can only edit your own recipes")
    return templates.TemplateResponse(request, "recipe_form.html", {
        "recipe": r, "styles": recipes.STYLES, "meals": recipes.MEALS,
        "form_action": f"/recipes/{rid}", "form_title": "Edit recipe",
        "nav": _nav(user),
    })


@router.post("/recipes/{rid}")
async def update(
    rid: str, request: Request,
    name: str = Form(...),
    style: str = Form(...),
    meal: str = Form(...),
    servings: str = Form("1"),
    prep_minutes: str = Form(""),
    cook_minutes: str = Form(""),
    ing_qty: list[str] = Form(default=[]),
    ing_unit: list[str] = Form(default=[]),
    ing_name: list[str] = Form(default=[]),
    steps: str = Form(""),
    prep_at_home: str = Form(""),
    gear: str = Form(""),
    tags: str = Form(""),
    notes: str = Form(""),
    image: Optional[UploadFile] = File(None),
    clear_image: str = Form(""),
    user: identity.User = Depends(require_user),
):
    r = recipes.get(rid)
    if r is None:
        raise HTTPException(status_code=404, detail="recipe not found")
    if r.author != user.id:
        raise HTTPException(status_code=403, detail="you can only edit your own recipes")
    image_bytes, image_mime = await _read_image(image)
    try:
        recipes.update(
            rid, name=name, style=style, meal=meal, servings=servings,
            prep_minutes=prep_minutes, cook_minutes=cook_minutes,
            ingredients=_parse_ingredients(ing_qty, ing_unit, ing_name),
            steps=steps, prep_at_home=prep_at_home, gear=gear, tags=tags, notes=notes,
            image=image_bytes, image_mime=image_mime,
            clear_image=bool(clear_image),
        )
    except recipes.RecipeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse(f"/recipes/{rid}", status_code=303)


@router.post("/recipes/{rid}/delete")
def delete(rid: str, user: identity.User = Depends(require_user)):
    r = recipes.get(rid)
    if r is None:
        raise HTTPException(status_code=404, detail="recipe not found")
    if r.author != user.id:
        raise HTTPException(status_code=403, detail="you can only delete your own recipes")
    recipes.delete(rid)
    return RedirectResponse("/recipes", status_code=303)
