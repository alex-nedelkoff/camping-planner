"""Supabase GoTrue auth calls (server-side, over httpx)."""
from __future__ import annotations

import httpx

from app import config


def _headers() -> dict:
    return {"apikey": config.SUPABASE_ANON_KEY or "",
            "Content-Type": "application/json"}


def _base() -> str:
    return (config.SUPABASE_URL or "").rstrip("/") + "/auth/v1"


def send_magic_link(email: str, redirect_to: str) -> None:
    r = httpx.post(f"{_base()}/otp",
                   json={"email": email, "options": {"email_redirect_to": redirect_to}},
                   headers=_headers(), timeout=15)
    r.raise_for_status()


def verify_token_hash(token_hash: str, type_: str) -> dict:
    r = httpx.post(f"{_base()}/verify",
                   json={"token_hash": token_hash, "type": type_},
                   headers=_headers(), timeout=15)
    r.raise_for_status()
    return r.json()


def refresh(refresh_token: str) -> dict:
    r = httpx.post(f"{_base()}/token?grant_type=refresh_token",
                   json={"refresh_token": refresh_token},
                   headers=_headers(), timeout=15)
    r.raise_for_status()
    return r.json()
