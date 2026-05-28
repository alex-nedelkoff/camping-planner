"""Shared Jinja2 templates instance with `static_version` global registered.

`static_version` is the current git HEAD short sha (or a timestamp fallback)
captured at import time. Templates append `?v={{ static_version }}` to
static asset URLs so browser caches invalidate on every deploy.
"""

from __future__ import annotations

import subprocess
import time

import markdown as _md
from fastapi.templating import Jinja2Templates

from app.config import JINJA_TEMPLATES_DIR


def _compute_static_version() -> str:
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=JINJA_TEMPLATES_DIR.parent.parent,
            capture_output=True, text=True, timeout=2, check=True,
        ).stdout.strip()
        if sha:
            return sha
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        pass
    return str(int(time.time()))


STATIC_VERSION = _compute_static_version()


def _md_filter(text: str) -> str:
    return _md.markdown(text or "", extensions=["extra", "sane_lists"])


def _reltime_filter(epoch: float) -> str:
    """Render a unix-epoch timestamp as a short relative string ('2h ago')."""
    try:
        delta = max(0, int(time.time() - float(epoch)))
    except (TypeError, ValueError):
        return ""
    for unit, secs in (("d", 86400), ("h", 3600), ("m", 60)):
        if delta >= secs:
            return f"{delta // secs}{unit} ago"
    return "just now"


templates = Jinja2Templates(directory=str(JINJA_TEMPLATES_DIR))
templates.env.globals["static_version"] = STATIC_VERSION
templates.env.filters["md"] = _md_filter
templates.env.filters["reltime"] = _reltime_filter
