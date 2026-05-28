"""Feedback board routes (ideas + bug reports)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.deps import require_user
from app.services import feedback, identity
from app.templating import templates

router = APIRouter()


@router.get("/feedback", response_class=HTMLResponse)
def feedback_page(request: Request, user: identity.User = Depends(require_user)):
    return templates.TemplateResponse(request, "feedback.html", {
        "posts": feedback.list_all(),
        "kinds": feedback.KINDS,
        "statuses": feedback.STATUSES,
        "current_user": user.id,
        "nav": {"home_href": "/", "user_email": user.email},
    })


@router.post("/feedback")
async def feedback_create(
    request: Request,
    kind: str = Form(...),
    body: str = Form(...),
    image: Optional[UploadFile] = File(None),
    user: identity.User = Depends(require_user),
):
    image_bytes: bytes | None = None
    image_mime: str | None = None
    if image is not None and image.filename:
        data = await image.read()
        if data:
            if not (image.content_type or "").startswith("image/"):
                raise HTTPException(status_code=400, detail="attachment must be an image")
            if len(data) > feedback.MAX_IMAGE_BYTES:
                raise HTTPException(status_code=400, detail="image too large (max 5 MB)")
            image_bytes, image_mime = data, image.content_type
    try:
        feedback.create(user.id, kind, body, image_bytes, image_mime)
    except feedback.FeedbackError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse("/feedback", status_code=303)


@router.post("/feedback/{fid}/status")
def feedback_set_status(fid: str, status: str = Form(...),
                        user: identity.User = Depends(require_user)):
    try:
        feedback.set_status(fid, status)
    except feedback.FeedbackError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse("/feedback", status_code=303)


@router.post("/feedback/{fid}/delete")
def feedback_delete(fid: str, user: identity.User = Depends(require_user)):
    post = feedback.get(fid)
    if post is None:
        raise HTTPException(status_code=404, detail="feedback not found")
    if post.author != user.id:
        raise HTTPException(status_code=403, detail="you can only delete your own posts")
    feedback.delete(fid)
    return RedirectResponse("/feedback", status_code=303)


@router.get("/feedback/{fid}/image")
def feedback_image(fid: str, user: identity.User = Depends(require_user)):
    img = feedback.get_image(fid)
    if img is None:
        raise HTTPException(status_code=404, detail="no image")
    data, mime = img
    return Response(content=data, media_type=mime)
