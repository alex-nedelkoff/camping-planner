#!/usr/bin/env python3
"""Compile a Camis park resources dump into a normalized site-survey JSON.

Browse-only reference data for the in-app Campsite Search. Availability is
intentionally NOT included (date-specific + rate-limited; the home-page
availability check covers that).

Add a future park:
    python3 scripts/compile_site_survey.py \
        --resources <raw_resources.json> \
        --park-slug balsam-lake \
        --park-name "Balsam Lake Provincial Park" \
        --out app/data/site_surveys/balsam-lake.json

Then commit the output file; it appears on /sites automatically.

Camis quirks handled here:
- Enum attributes store ints in definedAttributes[].values (a LIST); numeric
  attributes store a scalar in definedAttributes[].value.
- The attribute catalog maps enum ints to labels under each attribute's
  `values` list (entry keys: enumValue + localizedValues), NOT `enumValues`.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CATALOG = REPO / "api_attribute_filterable.json"

# Site-length attribute id, used for the equipment bucket heuristic.
SITE_LENGTH_ATTR_ID = -32743


def load_attr_defs(catalog_path) -> dict:
    """Build {attributeDefinitionId: {name, values:{enumInt: label}}}."""
    raw = json.loads(Path(catalog_path).read_text())
    defs = {}
    for a in (raw.values() if isinstance(raw, dict) else raw):
        if not isinstance(a, dict):
            continue
        aid = a.get("attributeDefinitionId")
        name = None
        for lv in (a.get("localizedValues") or []):
            if lv.get("cultureName", "").startswith("en"):
                name = lv.get("displayName") or lv.get("name")
                break
        if not name and a.get("localizedValues"):
            first = a["localizedValues"][0]
            name = first.get("displayName") or first.get("name")
        name = name or f"attr_{aid}"
        values = {}
        for v in (a.get("values") or []):
            vid = v.get("enumValue")
            vname = None
            for lv in (v.get("localizedValues") or []):
                if lv.get("cultureName", "").startswith("en"):
                    vname = lv.get("displayName") or lv.get("name")
                    break
            if not vname and v.get("localizedValues"):
                first = v["localizedValues"][0]
                vname = first.get("displayName") or first.get("name")
            values[vid] = vname or str(vid)
        defs[aid] = {"name": name, "values": values}
    return defs


def attr_get(da: dict, attr_defs: dict):
    """Return (name, value_or_label) for one definedAttributes entry."""
    aid = da.get("attributeDefinitionId")
    if aid not in attr_defs:
        return None, None
    name = attr_defs[aid]["name"]
    enum_vals = da.get("values") or []
    if enum_vals:
        labels = [attr_defs[aid]["values"].get(v, str(v)) for v in enum_vals]
        return name, (", ".join(labels) if len(labels) > 1 else labels[0])
    scalar = da.get("value")
    if scalar is not None:
        return name, scalar
    return name, None


def derive_campground_label(names: list) -> str:
    """Label a map group from its site-number range or name prefixes."""
    nums, prefixes = [], set()
    for n in names:
        m = re.match(r"^(\d+)", n)
        if m:
            nums.append(int(m.group(1)))
        pm = re.match(r"^([A-Za-z]+)", n)
        if pm:
            prefixes.add(pm.group(1))
    if nums:
        return f"Sites #{min(nums)}-{max(nums)} ({len(names)})"
    if "E" in prefixes:
        return f"E sites - electric ({len(names)})"
    if "T" in prefixes:
        return f"T sites ({len(names)})"
    if "Picnic" in prefixes:
        return f"Picnic shelters ({len(names)})"
    if "RA" in prefixes:
        return f"RA - roofed accommodation ({len(names)})"
    if any(p in prefixes for p in {"Bike", "Canoe", "Kayak", "Paddle", "SUP",
                                    "Water", "Floater", "Deposit"}):
        return f"Rentals - day-use ({len(names)})"
    if "DVP" in prefixes or "Bus" in prefixes:
        return f"Permits ({len(names)})"
    return f"Other ({len(names)})"


def equipment_bucket(s: dict) -> str:
    """Coarse equipment class from allowed-equipment count + site length."""
    n_eq = len(s.get("allowedEquipment") or [])
    length = None
    for da in (s.get("definedAttributes") or []):
        if da.get("attributeDefinitionId") == SITE_LENGTH_ATTR_ID:
            try:
                length = float(da.get("value") or 0) or None
            except (TypeError, ValueError):
                pass
    if n_eq == 0:
        return "Other / special"
    if length and length >= 24:
        return "RV / big rig"
    if n_eq >= 5 or (length and length >= 18):
        return "Trailer / motorhome"
    if n_eq >= 3:
        return "Small trailer / pop-up"
    return "Tent only"


def compile_survey(resources: dict, attr_defs: dict, park_slug: str,
                   park_name: str, pulled_on=None) -> dict:
    by_map = defaultdict(list)
    for _sid, s in resources.items():
        nm = (s.get("localizedValues") or [{}])[0].get("name") or ""
        mid = (s.get("mapIds") or [None])[0]
        by_map[mid].append(nm)
    campground_labels = {
        mid: derive_campground_label(names) for mid, names in by_map.items()
    }

    sites = []
    for _sid, s in resources.items():
        lv = (s.get("localizedValues") or [{}])[0]
        name = lv.get("name") or lv.get("displayName") or ""
        mid = (s.get("mapIds") or [None])[0]
        attributes = {}
        for da in (s.get("definedAttributes") or []):
            n, v = attr_get(da, attr_defs)
            if n and v is not None and v != "":
                attributes[n] = v
        photos = []
        for p in (s.get("photos") or []):
            urlres = p.get("photoUrlResult") or {}
            url = urlres.get("url") or urlres.get("avifUrl")
            if url:
                photos.append(url)
        sites.append({
            "name": name,
            "campground": campground_labels.get(mid, "Other"),
            "equipment_bucket": equipment_bucket(s),
            "description": lv.get("description") or "",
            "max_capacity": s.get("maxCapacity"),
            "attributes": attributes,
            "photos": photos,
        })
    sites.sort(key=lambda r: (r["campground"], r["name"]))
    return {
        "park_slug": park_slug,
        "park_name": park_name,
        "pulled_on": pulled_on or date.today().isoformat(),
        "site_count": len(sites),
        "sites": sites,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--resources", required=True)
    ap.add_argument("--park-slug", required=True)
    ap.add_argument("--park-name", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--catalog", default=str(CATALOG))
    ap.add_argument("--pulled-on", default=None)
    args = ap.parse_args()

    resources = json.loads(Path(args.resources).read_text())
    attr_defs = load_attr_defs(args.catalog)
    survey = compile_survey(resources, attr_defs, args.park_slug,
                            args.park_name, args.pulled_on)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(survey, indent=2, ensure_ascii=False))
    print(f"Wrote {out} - {survey['site_count']} sites")


if __name__ == "__main__":
    main()
