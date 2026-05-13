"""Mailer: assemble + send magic-link emails. Transport is mocked."""

import pytest

from app.services import mailer


class FakeTransport:
    def __init__(self):
        self.sent = []

    async def send(self, *, to, subject, html):
        self.sent.append({"to": to, "subject": subject, "html": html})


@pytest.mark.asyncio
async def test_send_magic_link_calls_transport_with_link():
    fake = FakeTransport()
    await mailer.send_magic_link(
        "alex@example.com",
        "https://example.test/login/verify?token=abc",
        transport=fake,
    )
    assert len(fake.sent) == 1
    msg = fake.sent[0]
    assert msg["to"] == "alex@example.com"
    assert "abc" in msg["html"]
    assert "Killarney" in msg["subject"] or "trip" in msg["subject"].lower()


@pytest.mark.asyncio
async def test_send_magic_link_html_has_clickable_button():
    fake = FakeTransport()
    url = "https://example.test/login/verify?token=xyz"
    await mailer.send_magic_link("a@b.com", url, transport=fake)
    html = fake.sent[0]["html"]
    assert f'href="{url}"' in html
