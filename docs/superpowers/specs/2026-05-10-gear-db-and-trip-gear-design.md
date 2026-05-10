# Gear DB & Trip-Page Gear Section — Design

**Date:** 2026-05-10
**Status:** Design — awaiting implementation plan
**Owner:** twolski
**Related work:** Mirrors the food-DB feature shipped under `docs/superpowers/specs/2026-05-10-food-db-and-meal-planner-design.md`. Read that first for shared rationale (storage choice, atomic writes, in-memory cache, dispatch pattern).

## Problem

The current per-trip gear section is a free-form markdown table with three columns (Item / Who's bringing / Notes). It has no shared catalog of items, no categories, no autocomplete, no weight tracking, and no aggregation across rows. Every trip re-types every item from scratch, common gear (canoe, stove, tarp) gets spelled differently across trips, and there's no way to see whether the load is balanced across people.

We want:

1. A persistent **gear catalog** (`gear.json`) of common camping gear, with a category and an optional weight per item.
2. A dedicated **`/gear` page** for managing the catalog (add / edit / delete items, manage categories), separate from any trip.
3. A revamped **per-trip gear table** that pulls from the catalog with autocomplete, computes total weight + per-person breakdown, and surfaces unknown-weight items.
4. Categorization (item → category, e.g. "Map" → "Navigation"), with categories themselves user-editable.

## Non-goals

- Personal packing list (`packing.md`) integration — out of scope, possible follow-up.
- Pack-volume / dimensions / cost-per-item.
- Gear "loadouts" (saved templates that apply to a trip).
- Bulk import from CSV / external sources.
- Weight unit conversion UI (we standardise on grams; UI shows kg in summaries).

## Architectural decision: storage

Same as the food-DB feature. The catalog and per-trip plan both live as **git-tracked files**:

| Data | Where | Why |
|---|---|---|
| Gear catalog | `gear.json` (repo root) | Same pattern as `parks.json` / `foods.json`. Git is the backup. |
| Per-trip gear plan | YAML frontmatter in `trips/<slug>/gear.md` | Same git-tracked pattern as `food.md`. Frontmatter is parsed; body below is regenerated for human reading. |
| Caches, checklist toggles | `camping.sqlite3` | Unchanged — operational only. |

The "DB is operational state only" rule is preserved.

## Components

### New files / modules

```
gear.json                                  ← new, git-tracked catalog (repo root)
app/services/gear.py                       ← load/search/upsert/delete + categories CRUD; mtime-invalidated cache
app/services/gear_plan.py                  ← read/write gear.md frontmatter; compute weight totals; render md body
app/routes/gear.py                         ← /api/gear CRUD + /api/gear/categories + /api/trip/{slug}/gear-plan
app/static/js/gear.js                      ← /gear page (master-detail UI + Manage Categories modal)
app/static/js/gear-plan.js                 ← trip-page gear section
app/static/css/gear.css                    ← /gear page styles (incl. category pill colors)
                                              (gear-plan styles fold into trip.css)
templates/trip-template/gear.md            ← updated to start with empty frontmatter
tests/test_gear_service.py                 ← new
tests/test_gear_plan_service.py            ← new
tests/test_gear_routes.py                  ← new
tests/test_gear_plan_routes.py             ← new
```

### Modified files

- `app/main.py` — register `gear` router(s).
- `app/routes/pages.py` — add `/gear` route.
- `app/templates/index.html` — sidebar "Gear DB" link, asset includes, `<template id="tpl-gear">`.
- `app/services/trips.py` — `load_trip_payload` marks gear section with `kind: "gear-plan"`; remove `"gear"` from `EDITABLE_SECTIONS`; `editable: False` on the gear section payload.
- `app/models.py` — Pydantic schemas (`GearItemIn/Out`, `GearCatalogResponse`, `CategoryRequest`, `GearPlanIn/Out`, `GearPlanItem`).
- `app/static/js/trip.js` — dispatch `kind: "gear-plan"` to `window.GearPlan.init` (parallel to the existing meal-plan dispatch).
- `app/static/js/index.js` — route `/gear` to `window.GearPage.mount`.
- `app/static/css/trip.css` — gear-plan section styles (mirroring `.mp-*` patterns: `.gp-header`, `.gp-row`, `.gp-pill`, etc.).
- `CLAUDE.md` — document the new feature.

## Data model

### `gear.json` (git-tracked, repo root)

```json
{
  "version": 1,
  "categories": [
    "Navigation", "Shelter", "Sleep", "Cook", "Water",
    "Food storage", "Safety", "Lighting", "Tools",
    "Paddling", "Clothing", "Other"
  ],
  "items": [
    {
      "id": "canoe-rental",
      "name": "Canoe (rental)",
      "category": "Paddling",
      "weight_g": 24500
    },
    {
      "id": "map-waterproof",
      "name": "Map (waterproof)",
      "category": "Navigation",
      "weight_g": 60
    }
  ]
}
```

**Field rules:**
- `id` — slug, generated from `name` on create. Immutable after creation. Lets the user rename without breaking trip references.
- `name` — required, non-empty after trim.
- `category` — required; must be in the top-level `categories` list.
- `weight_g` — **nullable** (key difference from food's required `kcal_per_serving`). When present, integer ≥ 0.
- `version` — bump if format changes.

**Slug collisions** on create resolve as `-2`, `-3`, etc.

**Categories:**
- The top-level `categories` array is user-editable from `/gear`.
- `"Other"` is the protected fallback. Server rejects rename or delete on `"Other"` with 400. Force-deletes of any other category reassign affected items to `"Other"`, so it must always exist.
- Add: appends to the array; rejects case-insensitive duplicates.
- Rename: rewrites every item that uses the old category to the new name (atomic write).
- Delete: 409 if any items reference; `?force=true` reassigns those items to `"Other"` and proceeds.

### `trips/<slug>/gear.md` (per-trip, git-tracked)

```yaml
---
items:
  - item_id: canoe-rental
    qty: 1
    who: shared
    notes: "rental from George Lake outfitter"
    override_weight_g: null
  - item_id: map-waterproof
    qty: 1
    who: Tom
    notes: ""
    override_weight_g: null
  - item_id: tarp-10x10
    qty: 1
    who: shared
    notes: ""
    override_weight_g: null
---

<!-- generated from frontmatter on save; edit via UI -->
# Shared gear

Total: **25,460 g (~25.5 kg)** — shared 25,400 g, Tom 60 g

| Item | Qty | Who | Weight | Notes |
|---|---|---|---|---|
| Canoe (rental) [Paddling] | 1 | shared | 24,500 g | rental from George Lake outfitter |
| Map (waterproof) [Navigation] | 1 | Tom | 60 g |  |
| Tarp 10×10 + ridgeline [Shelter] | 1 | shared | 900 g |  |
```

**Schema notes:**
- `items` is a flat list — no nesting (unlike food's day → meal → items).
- `qty` defaults to 1; multiplies the weight column. Integer ≥ 0.
- `who` is freeform string. UI surfaces a dropdown of `["shared", ...trip.participants]`.
- `notes` per-row is freeform.
- `override_weight_g` is rare — used when the trip is bringing a heavier or lighter version of a catalog item (e.g., "borrowed friend's lighter tarp"). Almost always `null`. The UI shows an inline toggle that flips the row into override mode.
- The body is regenerated on every save. Original markdown body preserved under `legacy_body` until first save (legacy banner pattern, see Migration).

### Computed values (never persisted)

`gear_plan.compute_totals(plan, catalog)` returns:

```python
{
  "items": [
    {**row,
     "weight_g_each": int | None,    # override_weight_g ?? catalog.weight_g
     "weight_g_total": int | None,   # weight_g_each * qty
     "unknown_weight": bool,         # True if both override and catalog are None
     "name": str | None,             # catalog name (None if catalog miss)
     "category": str | None,         # catalog category
     "unknown_item": bool,           # True if item_id not found in catalog
    }, ...
  ],
  "by_who": {"shared": int, "Tom": int, ...},  # sum of *known* weights
  "trip_g": int,
  "unknown_count": int,            # rows with unknown weight
}
```

If a row's `item_id` isn't in the catalog, the row is marked `unknown_item`: `name` and `category` are `None` and the UI displays the raw `item_id` with a yellow warning ("Item no longer in catalog — fix or remove this row"). The plan is **not** corrupted; the user can re-pick from the autocomplete or remove the row.

## API surface

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/gear` | SPA shell |
| `GET`  | `/api/gear` | full catalog `{categories, items}` |
| `POST` | `/api/gear` | create item; returns id |
| `PUT`  | `/api/gear/{id}` | update item |
| `DELETE` | `/api/gear/{id}?force=…` | delete; 409 if referenced; force succeeds |
| `GET`  | `/api/gear/refs/{id}` | trip slugs referencing this item |
| `POST` | `/api/gear/categories` | add category |
| `PUT`  | `/api/gear/categories/{old}` | rename category (rewrites items using it) |
| `DELETE` | `/api/gear/categories/{name}?force=…` | delete; 409 if used; force reassigns to `Other` |
| `GET`  | `/api/trip/{slug}/gear-plan` | gear plan + computed totals |
| `POST` | `/api/trip/{slug}/gear-plan` | replace gear plan; regenerates body |

**Route ordering** in `app/routes/gear.py`: more specific paths first to avoid latent collisions — `/refs/{id}`, `/categories`, `/categories/{old}` all before the generic `/{id}` routes.

## Service module shapes

### `app/services/gear.py`

```python
PROTECTED_CATEGORIES = {"Other"}

def load_catalog() -> dict
def search(query: str, category: str | None) -> list[dict]
def get(item_id: str) -> dict | None
def upsert(item: dict) -> str         # returns id; slugifies on create
def delete(item_id: str) -> None
def find_references(item_id: str) -> list[str]   # scans trips/*/gear.md

def add_category(name: str) -> None
def rename_category(old: str, new: str) -> None
def delete_category(name: str, force: bool = False) -> None
```

In-memory cache keyed by file mtime. `_invalidate_cache()` called after every mutation (matches the foods service pattern).

### `app/services/gear_plan.py`

```python
def load(slug: str) -> dict
def save(slug: str, plan: dict, catalog: dict) -> None
def compute_totals(plan: dict, catalog: dict) -> dict
def render_markdown_body(plan: dict, catalog: dict) -> str
```

`load()` on a `gear.md` with no frontmatter returns an empty plan with `legacy_body` populated.

## UI: `/gear` page (catalog management)

Two-pane layout, identical structure to `/foods`.

```
┌─────────────────────────────────────────────────────────────────────────┐
│  🔍 [           ]  Category: [▼ all]            [Manage categories…]    │
├──────────────────────────┬──────────────────────────────────────────────┤
│ Canoe (rental)          ▶│ Name                                         │
│   Paddling               │ [                                ]           │
│ MSR Pocket Rocket       ●│ Category   [Cook                 ▼]          │
│   Cook                   │ Weight (g) [   73   ] [✗ unk]                │
│ Map (waterproof)        ▶│                                              │
│   Navigation             │              [Save]    [× Delete]            │
│  ...                     │                                              │
│ + Add item               │                                              │
└──────────────────────────┴──────────────────────────────────────────────┘
```

**Behaviour:**
- Search is client-side, fuzzy on `name`. Category filter dropdown.
- Selection highlights one row; detail pane shows the form. Unsaved-change prompt on switch.
- "+ Add item" → blank detail pane → Save POSTs to `/api/gear`.
- **Weight field** has an "unknown" toggle (`[✗ unk]`). Clicking once greys the input and sets `weight_g: null` on save; clicking again re-enables.
- **Delete** → confirmation. If used by trips, 409 → confirmation listing trips → `?force=true` proceeds. Force-delete leaves a soft-broken reference in those trips (UI marks the row `unknown_item`).
- Validation errors surface as a red banner in the detail pane.
- **Category badges in the list** — small coloured pills next to each item name. Pill colour is a deterministic hash of the category name (consistent across reloads, no manual palette).

**Sidebar:** new "Gear DB" link below the existing "Foods DB" link.

### Manage categories modal

```
┌─Manage categories─────────────────────────────┐
│ Navigation                          [Rename]  │
│ Shelter                             [Rename]  │
│ Sleep                               [Rename]  │
│ Cook                                [Rename]  │
│ Water                               [Rename]  │
│ Food storage                        [× Delete]│
│ Safety                              [Rename]  │
│ Lighting                            [× Delete]│
│ Tools                               [Rename]  │
│ Paddling                            [Rename]  │
│ Clothing                            [Rename]  │
│ Other  (default — can't remove)               │
│                                               │
│ + Add category: [           ] [Add]   [Close] │
└───────────────────────────────────────────────┘
```

- **Add** — POST `/api/gear/categories`. Server appends if not duplicate (case-insensitive).
- **Rename** — inline edit, [Save]/[Cancel] inline. PUT `/api/gear/categories/{old}`. Server rewrites items.
- **Delete** — DELETE `/api/gear/categories/{name}`. 409 if any items use it; client offers "Reassign N items to 'Other' and delete?" → retries with `?force=true`.
- **`Other`** — protected: server rejects rename + delete with 400.

Validation:
- Category names: non-empty after trim, max 40 chars.
- Add rejects duplicates (case-insensitive).
- Rename rejects collision with another existing category.

## UI: trip-page gear section

Replaces the current `initTableEditor` flow for gear. Layout:

```
┌─Shared gear────────────────────────────────────────────────────────────┐
│                                                                        │
│  Total: 25,460 g (~25.5 kg)                                            │
│  shared 25,400 g  •  Tom 60 g  •  ⚠ 1 item with unknown weight         │
│                                                                        │
│  ┌──────────────────────┬─────┬─────┬──────────┬─────────┬─────┬──┐    │
│  │ Item                 │ Qty │ Wt  │ Total    │ Who     │Notes│  │    │
│  ├──────────────────────┼─────┼─────┼──────────┼─────────┼─────┼──┤    │
│  │ Canoe (rental)    ▼  │  1  │24500│ 24,500 g │ shared▼ │rent…│ ×│    │
│  │   ●Paddling                                                    │    │
│  ├──────────────────────┼─────┼─────┼──────────┼─────────┼─────┼──┤    │
│  │ Map (waterproof)  ▼  │  1  │  60 │     60 g │  Tom  ▼ │     │ ×│    │
│  │   ●Navigation                                                  │    │
│  ├──────────────────────┼─────┼─────┼──────────┼─────────┼─────┼──┤    │
│  │ Stove + fuel      ▼  │  1  │  ?  │      ? g │  Alex ▼ │     │ ×│    │
│  │   ●Cook   ⚠ unknown weight                                     │    │
│  └──────────────────────┴─────┴─────┴──────────┴─────────┴─────┴──┘    │
│                                                                        │
│  + add row                                            [ Save ]         │
└────────────────────────────────────────────────────────────────────────┘
```

(`●` = coloured category pill — same palette as the `/gear` page.)

**Per-row behaviour:**
- **Item** — autocomplete combobox sourced from `gear.json`. Type-to-filter; pick from list. If typed text doesn't match anything, an inline `+ Create '{name}' as new item` opens a modal (pre-fills name, blank weight + category, POSTs to `/api/gear`, selects the new id when done — same modal pattern as the meal-planner's create-food).
- **Qty** — integer input, default 1, min 0. Multiplies the weight column.
- **Wt** — read-only display of `(override_weight_g ?? catalog.weight_g)`, or `?` if both are null. Below it, a small **`[edit]`** link (inline, always visible) toggles the cell into a numeric input + `[↩ revert]` link. Editing writes to `override_weight_g`; reverting clears it back to null.
- **Total** — read-only computed: `weight_g_each × qty`. Shows `?` when weight is unknown.
- **Who** — dropdown of `["shared", ...trip.participants]`. Participants come from `trip.md` frontmatter (read at save-time and merged into the plan, mirroring the participant-injection fix from food).
- **Notes** — freeform text input.
- **× remove** — drops the row.

**Header summary:**
- Total (g + kg, kg shown to 1 dp).
- Per-person breakdown comma-list with `shared` first.
- ⚠ warning when any row has unknown weight: "N items with unknown weight" — clickable, scrolls to the first such row.

**+ add row** — appends `{item_id: "", qty: 1, who: "shared", notes: "", override_weight_g: null}`. Focus jumps to the new Item input.

**Save** — POSTs the entire `items` array to `/api/trip/{slug}/gear-plan`. Server regenerates the markdown body and rewrites `gear.md` atomically. "Saved." toast for ~2 s. Legacy banner clears once frontmatter exists.

**Empty state** — when `items: []`, show: *"No gear yet. Click + add row to start, or visit Gear DB to populate the catalog first."*

**Legacy editor button hidden** — the gear section gets `editable: False` in the trip payload, AND `"gear"` is removed from `EDITABLE_SECTIONS` in `app/services/trips.py`. Both changes are required: the first hides the button; the second blocks the API path so a stray `/api/save-section?section=gear` request can't corrupt the YAML. Regression test for the API block (parallels the food-bug fix from the prior feature).

## Migration of existing trips

Two existing trips have prose markdown tables in `gear.md` (`killarney-2026-05`, `killbear-2026-08`).

**Approach:** no automatic data migration. `load()` for a frontmatter-less file returns an empty plan + populated `legacy_body`. A banner appears whenever `legacy_body` is non-empty:

> *This trip has a gear table in `gear.md` that isn't in the new structured format. Saving will replace it — copy anything you want to keep first.* `[ View raw ]`

The "View raw" opens the existing markdown in a modal so the user can copy values manually. The user picks each row through the autocomplete, creating new catalog entries via the modal as needed. After first save, the body regenerates and the banner stops appearing (purely a function of the file's current state — no persistent dismiss flag).

## Seed `gear.json`

Ship with ~20 common items so the catalog isn't empty on first run. Categories = the 12 listed above. Items:

- **Paddling**: Canoe (rental), Paddle, PFD
- **Navigation**: Map (waterproof), Compass
- **Shelter**: Tent (3-person), Tarp 10×10 + ridgeline
- **Sleep**: Sleeping bag, Sleeping pad
- **Cook**: MSR Pocket Rocket stove, Cookpot + lid, Spork
- **Water**: Water filter, Nalgene 1 L
- **Food storage**: Bear barrel
- **Safety**: First aid kit
- **Lighting**: Headlamp
- **Tools**: Multitool, Lighter
- **Other**: Dry bag

Approximate weights from manufacturer specs where commonly known; left `null` where they vary widely (e.g. "Tent (3-person)").

## File-write safety

- `gear.json` and `gear.md` writes are atomic: tempfile in same dir, `os.replace`.
- In-memory catalog cache invalidated explicitly on every mutation (`_invalidate_cache()`); also auto-invalidates on file-mtime change for cross-process safety.
- `version` field on `gear.json` checked on load; unknown version aborts startup with a clear error.
- Frontmatter regex tolerates CRLF (the same pattern used in `meal_plan.py`).

## Testing

| Test file | Coverage |
|---|---|
| `test_gear_service.py` | catalog load/get/search/upsert/delete; slug collisions; mtime cache; `find_references` (incl. prefix-match regression test); category add/rename/delete (incl. blocking when in use, force reassigns to Other, can't delete `Other`) |
| `test_gear_plan_service.py` | frontmatter round-trip; CRLF tolerance; `compute_totals` (per-row, by_who, unknown_count, override_weight_g); `render_markdown_body` (per-row, totals line, weight unit formatting); `save` round-trips through `load`; `save` handles missing-from-catalog item_ids gracefully; participants pulled from trip.md (regression test for the food bug) |
| `test_gear_routes.py` | happy-path CRUD; validation errors (400); KeyError → 404; ref-blocked delete (409 → force); category routes (add/rename/delete + protections) |
| `test_gear_plan_routes.py` | GET returns scaffold for legacy trip with own fixture (avoids depending on repo state); POST round-trips; trip-payload `kind: "gear-plan"` integration; `editable: False` on gear section payload; legacy `/api/save-section?section=gear` blocked (regression test for the data-corruption bug we hit on food) |

All tests use a tmp `gear.json` and `trips/` directory (existing conftest pattern). No external mocks needed — gear catalog has no external API.

## Risks & known gaps

- **Body regeneration loses prose under headings.** Acceptable; documented in the file-head comment + first-load banner.
- **`id` is a slug from the *first* `name`.** If the user renames "Tent (3-person)" → "Tent (4-person)", the id `tent-3-person` becomes a misnomer but still works. Trip plans referencing the old id still resolve correctly.
- **No multi-user concurrent editing of `gear.json`.** Single-user app.
- **Single uvicorn worker assumed.** In-memory catalog cache is per-process; cross-worker invalidation not implemented.
- **Override-weight UI may feel cluttered.** `[edit]` link visible on every row. If usability is a problem in practice we can hide it behind hover. Visible on first cut for discoverability.

## Out-of-scope (deferred)

- Personal `packing.md` integration.
- Pack volume / dimensions / cost.
- Saved gear loadouts (templates).
- Bulk import from CSV / external sources.
- Cross-trip aggregation (e.g. "what's the heaviest item I bring on every trip?").
- Drag-reorder of rows.
- Weight unit toggle (lb/oz).
