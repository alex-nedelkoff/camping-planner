"""Cookbook (recipe repository) storage — dual-backend, like feedback/comments.

Recipes are site-wide content; each one is authored by a logged-in user, who is
the only one allowed to edit or delete it (enforced at the route layer).

`ingredients` and `tags` are stored as JSON (jsonb in Postgres, JSON-encoded TEXT
in SQLite). The service serializes/deserializes around that so callers always
see Python lists/dicts.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from app import config

STYLES = ("canoe", "car", "both")
MEALS = ("breakfast", "lunch", "dinner", "snack")
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MiB
MAX_NAME_LEN = 120


class RecipeError(ValueError):
    """Invalid recipe input (bad enum, empty name, oversized image, etc.)."""


@dataclass
class Recipe:
    id: str
    author: str
    name: str
    style: str
    meal: str
    servings: int
    prep_minutes: Optional[int]
    cook_minutes: Optional[int]
    ingredients: list[dict]
    steps: str
    prep_at_home: Optional[str]
    gear: Optional[str]
    tags: list[str]
    notes: Optional[str]
    has_image: bool
    created_at: float


# ---------------------------------------------------------------------------
# Validation / coercion
# ---------------------------------------------------------------------------

_QTY_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$")


def parse_qty(raw) -> Optional[float]:
    """Parse "1/2", "1.5", "1", "" -> float | None. Used both by form handling
    and as the canonical stored form for an ingredient's qty."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw) if raw != "" else None
    s = str(raw).strip()
    if not s:
        return None
    m = _QTY_RE.match(s)
    if m:
        num, den = int(m.group(1)), int(m.group(2))
        return num / den if den else None
    try:
        return float(s)
    except ValueError:
        return None


def _clean_ingredients(rows: list[dict]) -> list[dict]:
    """Drop empty rows; coerce qty to float|None; keep keys normalized."""
    out = []
    for r in rows or []:
        name = str(r.get("name", "")).strip()
        if not name:
            continue
        out.append({
            "qty": parse_qty(r.get("qty")),
            "unit": str(r.get("unit", "")).strip() or None,
            "name": name,
        })
    return out


def _clean_tags(raw) -> list[str]:
    if isinstance(raw, str):
        parts = [p.strip().lower() for p in raw.split(",")]
    else:
        parts = [str(t).strip().lower() for t in (raw or [])]
    seen, out = set(), []
    for p in parts:
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _validate(name, style, meal, servings, image, ingredients):
    name = (name or "").strip()
    if not name:
        raise RecipeError("name is required")
    if len(name) > MAX_NAME_LEN:
        raise RecipeError("name too long")
    if style not in STYLES:
        raise RecipeError(f"invalid style: {style!r}")
    if meal not in MEALS:
        raise RecipeError(f"invalid meal: {meal!r}")
    try:
        servings = int(servings)
    except (TypeError, ValueError):
        raise RecipeError("servings must be a whole number")
    if servings < 1:
        raise RecipeError("servings must be >= 1")
    if image is not None and len(image) > MAX_IMAGE_BYTES:
        raise RecipeError("image too large (max 5 MB)")
    if not isinstance(ingredients, list):
        raise RecipeError("ingredients must be a list")
    return name, style, meal, servings


def _coerce_int(value) -> Optional[int]:
    if value in (None, "", b""):
        return None
    try:
        v = int(value)
    except (TypeError, ValueError):
        return None
    return v if v >= 0 else None


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------


def _is_postgres() -> bool:
    return config.STORAGE_BACKEND == "postgres"


# Columns excluding `image` (kept off list/get for memory; fetched via get_image).
_LIST_COLS = ("id, author, name, style, meal, servings, prep_minutes, cook_minutes, "
              "ingredients, steps, prep_at_home, gear, tags, notes, "
              "(image is not null) as has_image, created_at")


def _row_to_recipe(r) -> Recipe:
    def load_json(val, default):
        if val in (None, ""):
            return default
        if isinstance(val, (list, dict)):
            return val
        return json.loads(val)
    return Recipe(
        id=r[0], author=r[1], name=r[2], style=r[3], meal=r[4],
        servings=int(r[5]),
        prep_minutes=r[6], cook_minutes=r[7],
        ingredients=load_json(r[8], []),
        steps=r[9] or "",
        prep_at_home=r[10],
        gear=r[11],
        tags=load_json(r[12], []),
        notes=r[13],
        has_image=bool(r[14]),
        created_at=float(r[15]),
    )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def create(*, author: str, name: str, style: str, meal: str, servings,
           prep_minutes=None, cook_minutes=None,
           ingredients=None, steps: str = "", prep_at_home: Optional[str] = None,
           gear: Optional[str] = None, tags=None, notes: Optional[str] = None,
           image: Optional[bytes] = None, image_mime: Optional[str] = None) -> str:
    ingredients = _clean_ingredients(ingredients or [])
    tags = _clean_tags(tags)
    name, style, meal, servings = _validate(name, style, meal, servings, image, ingredients)
    rid = uuid.uuid4().hex
    now = time.time()
    payload = (rid, author, name, style, meal, servings,
               _coerce_int(prep_minutes), _coerce_int(cook_minutes),
               json.dumps(ingredients), steps or "",
               (prep_at_home or None), (gear or None),
               json.dumps(tags), (notes or None),
               image, image_mime, now)
    if _is_postgres():
        from app.services import pg
        with pg.connection() as conn:
            conn.execute(
                "insert into recipes "
                "(id, author, name, style, meal, servings, prep_minutes, cook_minutes, "
                " ingredients, steps, prep_at_home, gear, tags, notes, image, image_mime, created_at) "
                "values (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s::jsonb,%s,%s,%s,%s)",
                payload)
    else:
        from app.services import db
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO recipes "
                "(id, author, name, style, meal, servings, prep_minutes, cook_minutes, "
                " ingredients, steps, prep_at_home, gear, tags, notes, image, image_mime, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                payload)
    return rid


def get(rid: str) -> Optional[Recipe]:
    if _is_postgres():
        from app.services import pg
        with pg.connection() as conn:
            row = conn.execute(
                f"select {_LIST_COLS} from recipes where id = %s", (rid,)).fetchone()
    else:
        from app.services import db
        with db.connect() as conn:
            row = conn.execute(
                f"SELECT {_LIST_COLS} FROM recipes WHERE id = ?", (rid,)).fetchone()
    return _row_to_recipe(row) if row else None


def get_image(rid: str) -> Optional[tuple[bytes, str]]:
    if _is_postgres():
        from app.services import pg
        with pg.connection() as conn:
            row = conn.execute(
                "select image, image_mime from recipes where id = %s", (rid,)).fetchone()
    else:
        from app.services import db
        with db.connect() as conn:
            row = conn.execute(
                "SELECT image, image_mime FROM recipes WHERE id = ?", (rid,)).fetchone()
    if not row or row[0] is None:
        return None
    return bytes(row[0]), (row[1] or "application/octet-stream")


def list_recipes(*, style: Optional[str] = None, meal: Optional[str] = None,
                 tag: Optional[str] = None, q: Optional[str] = None) -> list[Recipe]:
    """Filtered list, newest first. style/meal/q via SQL; tag filtered in Python
    (small dataset; avoids per-backend jsonb dance)."""
    where, args = [], []
    placeholder = "%s" if _is_postgres() else "?"
    if style in STYLES:
        where.append(f"style = {placeholder}"); args.append(style)
    if meal in MEALS:
        where.append(f"meal = {placeholder}"); args.append(meal)
    if q:
        like = "%" + q.lower() + "%"
        if _is_postgres():
            where.append("(lower(name) like %s or lower(ingredients::text) like %s)")
        else:
            where.append("(lower(name) LIKE ? OR lower(ingredients) LIKE ?)")
        args.extend([like, like])
    sql_where = (" WHERE " + " AND ".join(where)) if where else ""
    sql = f"select {_LIST_COLS} from recipes{sql_where} order by created_at desc"
    if _is_postgres():
        from app.services import pg
        with pg.connection() as conn:
            rows = conn.execute(sql, tuple(args)).fetchall()
    else:
        from app.services import db
        with db.connect() as conn:
            rows = conn.execute(sql.replace("select", "SELECT").replace(" from ", " FROM ")
                                .replace(" where ", " WHERE ").replace(" order by ", " ORDER BY "),
                                tuple(args)).fetchall()
    recipes = [_row_to_recipe(r) for r in rows]
    if tag:
        t = tag.strip().lower()
        recipes = [r for r in recipes if t in r.tags]
    return recipes


def update(rid: str, *, name: str, style: str, meal: str, servings,
           prep_minutes=None, cook_minutes=None,
           ingredients=None, steps: str = "", prep_at_home: Optional[str] = None,
           gear: Optional[str] = None, tags=None, notes: Optional[str] = None,
           image: Optional[bytes] = None, image_mime: Optional[str] = None,
           clear_image: bool = False) -> None:
    """Update everything-but-author. Image: leave alone unless `image` provided
    or `clear_image=True`."""
    ingredients = _clean_ingredients(ingredients or [])
    tags = _clean_tags(tags)
    name, style, meal, servings = _validate(name, style, meal, servings, image, ingredients)

    fields = ["name=%s", "style=%s", "meal=%s", "servings=%s",
              "prep_minutes=%s", "cook_minutes=%s",
              "ingredients=%s::jsonb", "steps=%s", "prep_at_home=%s",
              "gear=%s", "tags=%s::jsonb", "notes=%s"]
    args: list = [name, style, meal, servings,
                  _coerce_int(prep_minutes), _coerce_int(cook_minutes),
                  json.dumps(ingredients), steps or "", (prep_at_home or None),
                  (gear or None), json.dumps(tags), (notes or None)]
    if image is not None:
        fields += ["image=%s", "image_mime=%s"]
        args += [image, image_mime]
    elif clear_image:
        fields += ["image=NULL", "image_mime=NULL"]
    args.append(rid)

    if _is_postgres():
        from app.services import pg
        sql = f"update recipes set {', '.join(fields)} where id = %s"
        with pg.connection() as conn:
            conn.execute(sql, tuple(args))
    else:
        from app.services import db
        sqlite_fields = [f.replace("%s::jsonb", "?").replace("%s", "?") for f in fields]
        sql = f"UPDATE recipes SET {', '.join(sqlite_fields)} WHERE id = ?"
        with db.connect() as conn:
            conn.execute(sql, tuple(args))


def delete(rid: str) -> None:
    if _is_postgres():
        from app.services import pg
        with pg.connection() as conn:
            conn.execute("delete from recipes where id = %s", (rid,))
    else:
        from app.services import db
        with db.connect() as conn:
            conn.execute("DELETE FROM recipes WHERE id = ?", (rid,))
