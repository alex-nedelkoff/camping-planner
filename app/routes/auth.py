"""Magic-link login flow."""

from __future__ import annotations

import os

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import JINJA_TEMPLATES_DIR
from app.services import auth, mailer

router = APIRouter()
templates = Jinja2Templates(directory=str(JINJA_TEMPLATES_DIR))

SESSION_COOKIE = "cp_session"


def _base_url() -> str:
    return os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return templates.TemplateResponse(
        request, "login.html", {"sent": False},
    )


@router.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, email: str = Form(...)):
    email = email.strip().lower()
    token = auth.issue_magic_link(email)
    url = f"{_base_url()}/login/verify?token={token}"
    await mailer.send_magic_link(email, url)
    return templates.TemplateResponse(
        request, "login.html", {"sent": True, "email": email},
    )


@router.get("/login/verify")
async def login_verify(request: Request, token: str, next: str = "/"):
    try:
        session_id = auth.consume_magic_link(token)
    except auth.MagicLinkInvalid as e:
        raise HTTPException(status_code=400, detail=str(e))
    resp = RedirectResponse(url=next, status_code=303)
    resp.set_cookie(
        SESSION_COOKIE,
        session_id,
        max_age=auth.SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    return resp


@router.post("/logout")
async def logout(request: Request):
    sid = request.cookies.get(SESSION_COOKIE, "")
    if sid:
        auth.delete_session(sid)
    resp = RedirectResponse(url="/", status_code=303)
    resp.delete_cookie(SESSION_COOKIE)
    return resp
