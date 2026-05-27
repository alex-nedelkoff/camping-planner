"""Shared-password auth routes (username + site password)."""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import config
from app.services import identity
from app.templating import templates

router = APIRouter()


def _login_page(request: Request, error: str | None = None, status: int = 200):
    return templates.TemplateResponse(
        request, "login.html", {"nav": {}, "error": error}, status_code=status
    )


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return _login_page(request)


@router.post("/login")
def login_submit(request: Request,
                 username: str = Form(...), password: str = Form(...)):
    username = username.strip()
    if not config.SITE_PASSWORD:
        return _login_page(request, "Login is not configured yet.", status=503)
    if not username:
        return _login_page(request, "Please enter a name.", status=400)
    # Constant-time compare to avoid leaking the password via timing.
    import hmac
    if not hmac.compare_digest(password, config.SITE_PASSWORD):
        return _login_page(request, "Wrong password — try again.", status=401)
    resp = RedirectResponse("/", status_code=303)
    identity.set_session(resp, username)
    return resp


@router.post("/logout")
def logout(request: Request):
    resp = RedirectResponse("/login", status_code=303)
    identity.clear_session(resp)
    return resp
