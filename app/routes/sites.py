"""Campsite Search - browse-only per-park site reference pages."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.services import site_surveys
from app.templating import templates
from app.deps import require_user

router = APIRouter()

KEY_ATTRS = [
    "Privacy", "Quality", "Site Shade", "Site Length (m)", "Site Width (m)",
    "Ground Cover", "Pad Slope", "Shoreline Access", "Dogs Allowed",
    "Double Site", "Pull-through", "Fire Pit Available",
]


@router.get("/sites", response_class=HTMLResponse)
def sites_index(request: Request, user=Depends(require_user)):
    return templates.TemplateResponse(request, "sites_index.html", {
        "surveys": site_surveys.list_surveys(),
        "nav": {"home_href": "/", "user_email": user.email},
    })


@router.get("/sites/{slug}", response_class=HTMLResponse)
def sites_park(request: Request, slug: str, user=Depends(require_user)):
    survey = site_surveys.load_survey(slug)
    if survey is None:
        raise HTTPException(status_code=404, detail="No survey for that park")
    sites = survey.get("sites") or []
    return templates.TemplateResponse(request, "sites_park.html", {
        "survey": survey,
        "sites": sites,
        "filters": site_surveys.derive_filters(sites),
        "key_attrs": KEY_ATTRS,
        "nav": {"home_href": "/", "back_href": "/sites",
                "back_label": "All parks", "user_email": user.email},
    })
