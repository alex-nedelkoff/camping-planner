"""Magic-link auth routes (server-side)."""
from __future__ import annotations

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.services import auth, identity
from app.templating import templates

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"nav": {}})


@router.post("/login", response_class=HTMLResponse)
def login_submit(request: Request, email: str = Form(...)):
    redirect_to = str(request.base_url).rstrip("/") + "/auth/callback"
    try:
        auth.send_magic_link(email, redirect_to)
    except Exception:
        pass  # don't reveal whether the email exists
    return templates.TemplateResponse(request, "check_email.html",
                                      {"email": email, "nav": {}})


@router.get("/auth/callback")
def auth_callback(request: Request, token_hash: str = "",
                  link_type: str = Query("magiclink", alias="type")):
    resp = RedirectResponse("/", status_code=303)
    try:
        session = auth.verify_token_hash(token_hash, link_type)
        identity.set_session(resp, session["access_token"], session["refresh_token"])
    except Exception:
        return RedirectResponse("/login?error=1", status_code=303)
    return resp


@router.post("/logout")
def logout(request: Request):
    token = request.cookies.get(identity.ACCESS_COOKIE, "")
    if token:
        try:
            auth.signout(token)
        except Exception:
            pass
    resp = RedirectResponse("/login", status_code=303)
    identity.clear_session(resp)
    return resp
