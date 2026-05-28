import time

import pytest
from fastapi.testclient import TestClient

import app.config as config
from app.main import app
from app.services import db, feedback, identity
from app.services.identity import User

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32  # enough to look like image bytes


@pytest.fixture
def fbdb(monkeypatch, tmp_path):
    """Isolated SQLite-backed feedback store."""
    monkeypatch.setattr(config, "STORAGE_BACKEND", "filesystem")
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "fb.sqlite3")
    db.init_schema()
    return feedback


def _as(monkeypatch, name):
    monkeypatch.setattr(identity, "current_user",
                        lambda req, n=name: User(n, n) if n else None)


# ---- storage unit tests ----------------------------------------------------

def test_create_and_get_round_trip(fbdb):
    fid = fbdb.create("Alex", "idea", "  add a weight total  ")
    post = fbdb.get(fid)
    assert post.author == "Alex" and post.kind == "idea"
    assert post.body == "add a weight total"  # trimmed
    assert post.status == "open" and post.has_image is False


def test_list_newest_first(fbdb):
    a = fbdb.create("Alex", "idea", "first")
    time.sleep(0.01)
    b = fbdb.create("Jeff", "bug", "second")
    ids = [p.id for p in fbdb.list_all()]
    assert ids == [b, a]


def test_invalid_kind_rejected(fbdb):
    with pytest.raises(feedback.FeedbackError):
        fbdb.create("Alex", "praise", "nice app")


def test_empty_body_rejected(fbdb):
    with pytest.raises(feedback.FeedbackError):
        fbdb.create("Alex", "idea", "   ")


def test_oversized_image_rejected(fbdb):
    with pytest.raises(feedback.FeedbackError):
        fbdb.create("Alex", "bug", "big", image=b"\x00" * (feedback.MAX_IMAGE_BYTES + 1))


def test_image_round_trip(fbdb):
    fid = fbdb.create("Alex", "bug", "see pic", image=PNG, image_mime="image/png")
    assert fbdb.get(fid).has_image is True
    data, mime = fbdb.get_image(fid)
    assert data == PNG and mime == "image/png"


def test_get_image_none_when_absent(fbdb):
    fid = fbdb.create("Alex", "idea", "no pic")
    assert fbdb.get_image(fid) is None


def test_set_status_and_invalid(fbdb):
    fid = fbdb.create("Alex", "idea", "x")
    fbdb.set_status(fid, "planned")
    assert fbdb.get(fid).status == "planned"
    with pytest.raises(feedback.FeedbackError):
        fbdb.set_status(fid, "wontfix")


def test_delete(fbdb):
    fid = fbdb.create("Alex", "idea", "x")
    fbdb.delete(fid)
    assert fbdb.get(fid) is None


# ---- route / authz tests ---------------------------------------------------

def test_anonymous_redirected(fbdb, monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    _as(monkeypatch, None)
    c = TestClient(app)
    r = c.get("/feedback", follow_redirects=False)
    assert r.status_code == 303 and "/login" in r.headers.get("location", "")
    assert c.post("/feedback", data={"kind": "idea", "body": "hi"},
                  follow_redirects=False).status_code == 401


def test_post_appears_in_list(fbdb, monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    _as(monkeypatch, "Alex")
    c = TestClient(app)
    r = c.post("/feedback", data={"kind": "idea", "body": "weight total please"},
               follow_redirects=False)
    assert r.status_code == 303
    page = c.get("/feedback").text
    assert "weight total please" in page and "Alex" in page


def test_post_with_image_served(fbdb, monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    _as(monkeypatch, "Jeff")
    c = TestClient(app)
    c.post("/feedback", data={"kind": "bug", "body": "screenshot"},
           files={"image": ("s.png", PNG, "image/png")})
    fid = feedback.list_all()[0].id
    img = c.get(f"/feedback/{fid}/image")
    assert img.status_code == 200
    assert img.headers["content-type"].startswith("image/png")
    assert img.content == PNG


def test_status_change_route(fbdb, monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    _as(monkeypatch, "Alex")
    c = TestClient(app)
    c.post("/feedback", data={"kind": "idea", "body": "x"})
    fid = feedback.list_all()[0].id
    c.post(f"/feedback/{fid}/status", data={"status": "done"}, follow_redirects=False)
    assert feedback.get(fid).status == "done"


def test_delete_own_vs_others(fbdb, monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    _as(monkeypatch, "Alex")
    c = TestClient(app)
    c.post("/feedback", data={"kind": "idea", "body": "alex post"})
    fid = feedback.list_all()[0].id
    # Jeff cannot delete Alex's post
    _as(monkeypatch, "Jeff")
    assert c.post(f"/feedback/{fid}/delete", follow_redirects=False).status_code == 403
    # Alex can
    _as(monkeypatch, "Alex")
    assert c.post(f"/feedback/{fid}/delete", follow_redirects=False).status_code == 303
    assert feedback.get(fid) is None


def test_invalid_kind_and_bad_uploads(fbdb, monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    _as(monkeypatch, "Alex")
    c = TestClient(app)
    assert c.post("/feedback", data={"kind": "nope", "body": "x"}).status_code == 400
    assert c.post("/feedback", data={"kind": "bug", "body": "x"},
                  files={"image": ("f.txt", b"hello", "text/plain")}).status_code == 400
    big = b"\x00" * (feedback.MAX_IMAGE_BYTES + 1)
    assert c.post("/feedback", data={"kind": "bug", "body": "x"},
                  files={"image": ("big.png", big, "image/png")}).status_code == 400
