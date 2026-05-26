"""Per-park image assets, discovered by slug convention.

Layout:  app/static/img/parks/<slug>/{hero.*, campground-map.*, park-map.*}
Pure filesystem reads; never raises. Adding a park = drop files in its dir.
"""
from __future__ import annotations

from app.config import STATIC_DIR

PARKS_IMG_DIR = STATIC_DIR / "img" / "parks"
DEFAULT_HERO = "/static/img/killarney-hero.jpg"

# (filename stem, display title) in display order — campground first.
_MAP_KINDS = [("campground-map", "Campground map"), ("park-map", "Park map")]
_IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp")


def _find(slug: str, stem: str) -> str | None:
    """Return the /static URL for <slug>/<stem>.<ext> if a file exists."""
    base = PARKS_IMG_DIR / slug
    for ext in _IMG_EXTS:
        if (base / f"{stem}{ext}").is_file():
            return f"/static/img/parks/{slug}/{stem}{ext}"
    return None


def hero_image(slug: str) -> str:
    """Per-park hero URL if a hero.* file exists, else the default hero."""
    return _find(slug, "hero") or DEFAULT_HERO


def park_maps(slug: str) -> list[dict]:
    """List of {title, url} for whichever map images exist (campground first)."""
    out = []
    for stem, title in _MAP_KINDS:
        url = _find(slug, stem)
        if url:
            out.append({"title": title, "url": url})
    return out
