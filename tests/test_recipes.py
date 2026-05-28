import pytest
from fastapi.testclient import TestClient

import app.config as config
from app.main import app
from app.services import db, identity, recipes
from app.services.identity import User

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.fixture
def store(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "STORAGE_BACKEND", "filesystem")
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "r.sqlite3")
    db.init_schema()
    return recipes


def _as(monkeypatch, name):
    monkeypatch.setattr(identity, "current_user",
                        lambda req, n=name: User(n, n) if n else None)


def _mk(store, **over):
    args = dict(author="Alex", name="Chili", style="canoe", meal="dinner", servings=4,
                ingredients=[{"qty": "1", "unit": "cup", "name": "beans"}],
                steps="Boil. Eat.", tags="vegan, one-pot")
    args.update(over)
    return store.create(**args)


# ---- parse_qty -------------------------------------------------------------

def test_parse_qty_fractions_decimals_empty():
    assert recipes.parse_qty("1/2") == 0.5
    assert recipes.parse_qty("1.5") == 1.5
    assert recipes.parse_qty("3") == 3.0
    assert recipes.parse_qty("") is None
    assert recipes.parse_qty(None) is None
    assert recipes.parse_qty("garbage") is None


# ---- storage round-trips ---------------------------------------------------

def test_create_and_get(store):
    rid = _mk(store)
    r = store.get(rid)
    assert r.author == "Alex" and r.name == "Chili"
    assert r.style == "canoe" and r.meal == "dinner" and r.servings == 4
    assert r.tags == ["vegan", "one-pot"]
    assert r.ingredients == [{"qty": 1.0, "unit": "cup", "name": "beans"}]
    assert r.has_image is False


def test_invalid_enums_rejected(store):
    with pytest.raises(recipes.RecipeError):
        _mk(store, style="motorhome")
    with pytest.raises(recipes.RecipeError):
        _mk(store, meal="brunch")


def test_empty_name_rejected(store):
    with pytest.raises(recipes.RecipeError):
        _mk(store, name="   ")


def test_oversized_image_rejected(store):
    with pytest.raises(recipes.RecipeError):
        _mk(store, image=b"\x00" * (recipes.MAX_IMAGE_BYTES + 1))


def test_empty_ingredient_rows_dropped(store):
    rid = _mk(store, ingredients=[
        {"qty": "1", "unit": "cup", "name": "beans"},
        {"qty": "", "unit": "", "name": "   "},   # dropped
        {"qty": "1/2", "unit": "tbsp", "name": "chili powder"},
    ])
    r = store.get(rid)
    assert [i["name"] for i in r.ingredients] == ["beans", "chili powder"]
    assert r.ingredients[1]["qty"] == 0.5


def test_filters(store):
    _mk(store, author="Alex", name="Chili",  style="canoe", meal="dinner",  tags="one-pot, vegan")
    _mk(store, author="Sam",  name="Pasta",  style="car",   meal="dinner",  tags="quick")
    _mk(store, author="Jeff", name="Oats",   style="both",  meal="breakfast", tags="quick")
    assert [r.name for r in store.list_recipes(style="canoe")] == ["Chili"]
    assert sorted(r.name for r in store.list_recipes(meal="dinner")) == ["Chili", "Pasta"]
    assert sorted(r.name for r in store.list_recipes(tag="quick")) == ["Oats", "Pasta"]
    assert [r.name for r in store.list_recipes(q="chil")] == ["Chili"]
    assert sorted(r.name for r in store.list_recipes()) == ["Chili", "Oats", "Pasta"]


def test_update_preserves_author(store):
    rid = _mk(store, author="Alex", name="Chili")
    store.update(rid, name="Better chili", style="canoe", meal="dinner", servings=6,
                 ingredients=[{"qty": "2", "unit": "cup", "name": "beans"}],
                 steps="Better.", tags="vegan")
    r = store.get(rid)
    assert r.author == "Alex" and r.name == "Better chili" and r.servings == 6


def test_image_round_trip(store):
    rid = _mk(store, image=PNG, image_mime="image/png")
    assert store.get(rid).has_image is True
    data, mime = store.get_image(rid)
    assert data == PNG and mime == "image/png"


def test_delete(store):
    rid = _mk(store)
    store.delete(rid)
    assert store.get(rid) is None


# ---- routes / authz --------------------------------------------------------

def test_anonymous_redirected(store, monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    _as(monkeypatch, None)
    c = TestClient(app)
    r = c.get("/recipes", follow_redirects=False)
    assert r.status_code == 303 and "/login" in r.headers.get("location", "")


def test_index_renders_and_filters(store, monkeypatch):
    _mk(store, author="Alex", name="Chili", style="canoe")
    _mk(store, author="Sam",  name="Pasta", style="car")
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    _as(monkeypatch, "Alex")
    c = TestClient(app)
    page = c.get("/recipes").text
    assert "Chili" in page and "Pasta" in page
    page = c.get("/recipes?style=canoe").text
    assert "Chili" in page and "Pasta" not in page


def test_create_via_form(store, monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    _as(monkeypatch, "Alex")
    c = TestClient(app)
    r = c.post("/recipes", data={
        "name": "Trail bars", "style": "canoe", "meal": "snack", "servings": "8",
        "ing_qty": ["1", ""], "ing_unit": ["cup", ""], "ing_name": ["oats", "  "],
        "steps": "Mix.", "tags": "no-cook, quick",
    }, follow_redirects=False)
    assert r.status_code == 303
    rid = r.headers["location"].split("/")[-1]
    rec = recipes.get(rid)
    assert rec.name == "Trail bars" and rec.author == "Alex"
    assert [i["name"] for i in rec.ingredients] == ["oats"]
    assert rec.tags == ["no-cook", "quick"]


def test_edit_authz(store, monkeypatch):
    rid = _mk(store, author="Alex")
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    _as(monkeypatch, "Jeff")
    c = TestClient(app)
    assert c.get(f"/recipes/{rid}/edit", follow_redirects=False).status_code == 403
    assert c.post(f"/recipes/{rid}", data={
        "name": "Hijack", "style": "canoe", "meal": "dinner", "servings": "4",
        "steps": "no",
    }, follow_redirects=False).status_code == 403
    _as(monkeypatch, "Alex")
    r = c.post(f"/recipes/{rid}", data={
        "name": "Renamed", "style": "canoe", "meal": "dinner", "servings": "4",
        "ing_qty": ["1"], "ing_unit": ["cup"], "ing_name": ["beans"],
        "steps": "Boil.",
    }, follow_redirects=False)
    assert r.status_code == 303 and recipes.get(rid).name == "Renamed"


def test_delete_authz(store, monkeypatch):
    rid = _mk(store, author="Alex")
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    _as(monkeypatch, "Jeff")
    c = TestClient(app)
    assert c.post(f"/recipes/{rid}/delete", follow_redirects=False).status_code == 403
    _as(monkeypatch, "Alex")
    assert c.post(f"/recipes/{rid}/delete", follow_redirects=False).status_code == 303
    assert recipes.get(rid) is None


def test_image_served_through_route(store, monkeypatch):
    rid = _mk(store, image=PNG, image_mime="image/png")
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    _as(monkeypatch, "Alex")
    c = TestClient(app)
    r = c.get(f"/recipes/{rid}/image")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")
    assert r.content == PNG
