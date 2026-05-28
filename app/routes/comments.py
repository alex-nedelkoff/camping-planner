"""Per-trip comments API (JSON; consumed by static/js/comments.js)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.models import (CommentCreateRequest, CommentItem, CommentResponse,
                        CommentsResponse, OkResponse)
from app.services import comments, identity
from app.deps import require_user

router = APIRouter(prefix="/api")


def _ensure_trip(slug: str) -> None:
    from app.services import trip_repo
    if not slug or not trip_repo.get_repo().exists(slug):
        raise HTTPException(status_code=404, detail={"ok": False, "error": "trip not found"})


def _item(c: comments.Comment, user: identity.User) -> CommentItem:
    return CommentItem(id=c.id, author=c.author, body=c.body,
                       created_at=c.created_at, mine=(c.author == user.id))


@router.get("/trips/{slug}/comments", response_model=CommentsResponse)
def list_comments(slug: str, user: identity.User = Depends(require_user)):
    _ensure_trip(slug)
    return CommentsResponse(comments=[_item(c, user) for c in comments.list_for(slug)])


@router.post("/trips/{slug}/comments", response_model=CommentResponse)
def add_comment(slug: str, body: CommentCreateRequest,
                user: identity.User = Depends(require_user)):
    _ensure_trip(slug)
    try:
        c = comments.create(slug, user.id, body.body)
    except comments.CommentError as e:
        raise HTTPException(status_code=400, detail={"ok": False, "error": str(e)})
    return CommentResponse(comment=_item(c, user))


@router.delete("/trips/{slug}/comments/{comment_id}", response_model=OkResponse)
def delete_comment(slug: str, comment_id: str,
                   user: identity.User = Depends(require_user)):
    c = comments.get(comment_id)
    if c is None or c.trip_slug != slug:
        raise HTTPException(status_code=404, detail={"ok": False, "error": "comment not found"})
    if c.author != user.id:
        raise HTTPException(status_code=403, detail={"ok": False, "error": "not your comment"})
    comments.delete(comment_id)
    return OkResponse()
