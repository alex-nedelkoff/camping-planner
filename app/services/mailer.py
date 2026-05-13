"""Email transport for magic-link delivery.

Production uses Resend's HTTP API. Tests pass a fake `transport` with
the same `.send(to, subject, html)` interface.
"""

from __future__ import annotations

import os
from typing import Protocol

import httpx


class Transport(Protocol):
    async def send(self, *, to: str, subject: str, html: str) -> None: ...


class ResendTransport:
    """Default production transport. Reads API key from env."""

    def __init__(self, api_key: str | None = None, mail_from: str | None = None):
        self.api_key = api_key or os.environ["RESEND_API_KEY"]
        self.mail_from = mail_from or os.environ["MAIL_FROM"]

    async def send(self, *, to: str, subject: str, html: str) -> None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "from": self.mail_from,
                    "to": [to],
                    "subject": subject,
                    "html": html,
                },
            )
            r.raise_for_status()


_DEFAULT: Transport | None = None


def default_transport() -> Transport:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = ResendTransport()
    return _DEFAULT


def _render_magic_link_html(login_url: str) -> str:
    return f"""\
<!doctype html>
<html><body style="font-family:system-ui,sans-serif;color:#222;
                   max-width:480px;margin:2rem auto;padding:1rem;">
  <h1 style="font-family:Fraunces,Georgia,serif;color:#1f3a3a;">
    Killarney trip planner
  </h1>
  <p>Click the button below to sign in. The link expires in 15 minutes.</p>
  <p>
    <a href="{login_url}"
       style="display:inline-block;background:#2d5016;color:white;
              padding:.75rem 1.25rem;border-radius:6px;
              text-decoration:none;">Sign in</a>
  </p>
  <p style="color:#666;font-size:.9rem;">
    If you didn't ask for this, ignore the email.
  </p>
</body></html>
"""


async def send_magic_link(
    to: str,
    login_url: str,
    *,
    transport: Transport | None = None,
) -> None:
    tx = transport or default_transport()
    await tx.send(
        to=to,
        subject="Your Killarney trip planner sign-in link",
        html=_render_magic_link_html(login_url),
    )
