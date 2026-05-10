# Food DB & Per-Trip Meal Planner — Design

**Date:** 2026-05-10
**Status:** Design — awaiting implementation plan
**Owner:** twolski

## Problem

The current per-trip food section is unstructured prose: markdown headers per meal, a "_meal idea_ — _who_" placeholder, and no calorie tracking, no quantity, no shared catalog of foods, no way to know whether the planned food matches the trip's energy demand.

We want:

1. A persistent **foods catalog** of items commonly brought camping (freeze-dried meals, canned fish, instant mash, snacks, drinks).
2. A **per-trip meal planner** that breaks the trip into day × meal rows of food items pulled from the catalog, with live calorie totals.
3. A **calorie target** computed from days × people × activity-level intensity, displayed against the planned total.
4. A **clean editable UI** — autocomplete on food names, edit-in-place, recoverable from mistakes.
5. A dedicated **`/foods` page** for managing the catalog, separate from trip pages but feeding their food sections.

## Non-goals

- Macro tracking (protein/fat/carbs).
- Pack weight or cost-per-trip calculations.
- GPX-derived calorie estimates.
- Sharing the catalog across machines / multi-user concurrent editing.
- Reminders, shopping lists, or grocery integration.

Each is a possible follow-up; none are in v1.

## Architectural decision: storage

The foods catalog and per-trip meal plan are both **stored as git-tracked files**, matching the existing project rule that `camping.sqlite3` holds operational state only:

| Data | Where | Why |
|---|---|---|
| Foods catalog | `foods.json` (repo root) | Same pattern as `parks.json`. Git is the backup. ~hundreds of items max — JSON is fast enough. |
| Per-trip meal plan | YAML frontmatter in `trips/<slug>/food.md` | Same git-tracked pattern as the rest of the trip. Frontmatter is parsed; body below is regenerated for human reading. |
| Caches, checklist toggles | `camping.sqlite3` | Unchanged — operational only. |

**Rejected alternative:** putting the foods catalog in SQLite. It implied a third storage philosophy, required a new backup subsystem, introduced cross-format referential-integrity work (md → DB), and added schema-migration overhead. None of those costs are justified at the data scale we expect (≤ 500 foods).

**Implication:** the original "DB is operational state only" rule is preserved. The previously-considered backup feature is not needed.

## Components

### New files / modules

```
foods.json                                 ← new, git-tracked catalog (repo root)
app/services/foods.py                      ← load/search/upsert/delete; in-memory cache, mtime-invalidated
app/services/meal_plan.py                  ← read/write food.md frontmatter; compute totals; render md body
app/routes/foods.py                        ← /api/foods CRUD + /api/trip/{slug}/meals
app/static/js/foods.js                     ← /foods page (master-detail UI)
app/static/js/meal-plan.js                 ← trip-page meal-planner section
app/static/css/foods.css                   ← /foods styles (meal-plan styles fold into trip.css)
templates/trip-template/food.md            ← updated to start with empty frontmatter
tests/test_foods_service.py                ← new
tests/test_meal_plan_service.py            ← new
tests/test_foods_routes.py                 ← new
tests/test_meal_plan_integration.py        ← end-to-end via routes
```

### Modified files

- `app/main.py` — register the new `foods` router.
- `app/routes/pages.py` — `/foods` route serves the SPA shell (existing pattern).
- `app/routes/trips.py` — `load_trip_payload` flags the food section so the SPA renders the meal planner instead of raw HTML.
- `app/services/trips.py` — `load_trip_payload` may need a `kind: "meal-plan"` marker on the food section.
- `app/static/js/index.js` — sidebar gets a "Foods" link alongside "Availability"; SPA router handles `/foods`.
- `app/static/js/trip.js` — when a section has `kind: "meal-plan"`, hand it off to `meal-plan.js`.

## Data model

### `foods.json` (git-tracked, repo root)

```json
{
  "version": 1,
  "categories": ["meal", "snack", "drink", "condiment", "other"],
  "foods": [
    {
      "id": "mountain-house-lasagna",
      "name": "Mountain House Lasagna with Meat Sauce",
      "category": "meal",
      "kcal_per_serving": 570,
      "serving_size": "1 pouch (113 g)",
      "url": "https://mountainhouse.com/products/lasagna-with-meat-sauce"
    }
  ]
}
```

**Field rules:**
- `id` — slug, generated from `name` on create. **Immutable after creation.** Lets a user rename a food without breaking existing meal plans.
- `name` — required, non-empty after trim. Used for display + autocomplete.
- `category` — required; must be in the top-level `categories` list.
- `kcal_per_serving` — required, integer ≥ 0.
- `serving_size` — required, free-text label ("1 pouch (113 g)", "2 cups dry"). Not parsed.
- `url` — optional; if present, must look like `http(s)://…`.
- `version` — bump if the file format ever needs migration.

**Slug collisions** on create are resolved by appending `-2`, `-3`, etc.

### `trips/<slug>/food.md` (per-trip, git-tracked)

```yaml
---
calorie_target:
  activity_level: backcountry            # backcountry | bikepacking | boat-camping | car-camping
  kcal_per_person_per_day: 4000          # default from activity_level; user-editable
days:
  - date: 2026-07-10
    label: Friday
    meals:
      - meal: dinner
        items:
          - food_id: mountain-house-lasagna
            servings: 2
            who: Tom
            note: ""
  - date: 2026-07-11
    label: Saturday
    meals:
      - meal: breakfast
        items:
          - food_id: instant-oatmeal-pkt
            servings: 4
            who: shared
---

<!-- generated from frontmatter on save; edit via UI -->
# Food plan

Calorie target: **4000 kcal/person/day × 3 people × 3 days = 36,000 kcal**

## Friday (2026-07-10) — 1140 kcal
- **Dinner** — Mountain House Lasagna × 2 (1140 kcal) — Tom

## Saturday (2026-07-11) — 480 kcal
- **Breakfast** — Instant oatmeal pkt × 4 (480 kcal) — shared
```

The body is **regenerated on every save** from the frontmatter. Hand-edited prose under headings is lost on next save. Documented via the file-head comment and a first-load banner (see Migration).

### Activity-level → kcal/person/day defaults

| Level | Default kcal | Reasoning |
|---|---|---|
| `backcountry` | 4000 | Paddling/portaging/hiking, full days |
| `bikepacking` | 4500 | Continuous endurance effort, often the hungriest |
| `boat-camping` | 3500 | Some paddling but base-camped |
| `car-camping` | 2500 | Low activity, normal life + walking |

User can override `kcal_per_person_per_day` per-trip after picking a level.

### Computed values (never persisted)

`meal_plan.compute_totals(plan, catalog)` returns:

- per-meal kcal = `Σ(servings × foods[food_id].kcal_per_serving)`
- per-day kcal = `Σ(meal kcals)`
- trip total kcal = `Σ(day kcals)`
- target kcal = `len(days) × len(participants) × kcal_per_person_per_day`
- delta = `total − target`

If `food_id` doesn't resolve in `foods.json`, the row's kcal is `None`, marked `?` in the UI, and a warning surfaces. Meal plan is *not* corrupted — user can edit the row.

## API surface

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/foods` | SPA page (same shell as everything else) |
| `GET`  | `/api/foods` | full catalog `{categories, foods}` |
| `POST` | `/api/foods` | create one; returns the new id |
| `PUT`  | `/api/foods/{id}` | update fields |
| `DELETE` | `/api/foods/{id}` | delete; query param `?force=true` to skip ref-check |
| `GET`  | `/api/foods/refs/{id}` | list trip slugs referencing this food |
| `GET`  | `/api/trip/{slug}/meals` | meal plan frontmatter as JSON |
| `POST` | `/api/trip/{slug}/meals` | replace meal plan; regenerates body |

The trip pane continues to be served via `/api/trip/{slug}`. The food section in the payload gets a `kind: "meal-plan"` marker so the SPA hands it to `meal-plan.js` instead of rendering raw HTML.

## Service module shapes

### `app/services/foods.py`

```python
def load_catalog() -> dict
def search(query: str, category: str | None) -> list[dict]
def get(food_id: str) -> dict | None
def upsert(food: dict) -> str         # returns id; slugifies on create
def delete(food_id: str) -> None
def find_references(food_id: str) -> list[str]   # scans trips/*/food.md
```

In-memory cache keyed by file mtime. Reload on first call after mtime change.

### `app/services/meal_plan.py`

```python
def load(slug: str) -> dict
def save(slug: str, plan: dict) -> None
def compute_totals(plan: dict, catalog: dict) -> dict
def render_markdown_body(plan: dict, catalog: dict) -> str

ACTIVITY_DEFAULTS = {
    "backcountry": 4000,
    "bikepacking": 4500,
    "boat-camping": 3500,
    "car-camping": 2500,
}
```

`load(slug)` on a `food.md` with no frontmatter returns an empty plan with day cards generated from the trip's `start_date`/`end_date`.

## UI: `/foods` page (master-detail)

Two-pane layout. Sidebar (existing) on the far left; main area is `[search/filter bar]` over `[list 40%] | [detail form 60%]`.

```
┌──────────────────────────────────────────────────────────────┐
│  🔍 [           ]  Category: [▼ all]                          │
├────────────────────────┬─────────────────────────────────────┤
│ Clif Bar              ▶│ Name                                │
│ Instant mash          ▶│ [                                  ]│
│ Mountain House Lasagna●│ Category   [meal              ▼]    │
│ Tuna pouch            ▶│ kcal/serving [   570 ]              │
│  ...                   │ Serving size [1 pouch (113 g)     ] │
│ + Add food             │ URL          [https://...        ] ↗│
│                        │                                     │
│                        │              [Save]    [× Delete]   │
└────────────────────────┴─────────────────────────────────────┘
```

**Behaviour:**
- Search is client-side, fuzzy on `name`. Category filter is a dropdown.
- Selection highlights one row; detail pane shows its form. Unsaved-changes prompt on switch.
- "+ Add food" → blank detail pane → Save POSTs to `/api/foods`.
- Delete → confirmation dialog. If `find_references` returns trips, list them and offer Cancel / Delete anyway. Force-delete leaves a broken-ref warning in those plans.
- URL field exposes "open ↗" link when populated.
- Validation errors surface as a red banner in the detail pane.

**Sidebar:** new "Foods" link in the SPA sidebar above/below the existing "Availability" link.

## UI: trip-page meal planner

Replaces the current rendered `food.md` markdown. Layout:

```
┌─Food plan────────────────────────────────────────────────────────┐
│  Activity: [Backcountry ▼]    Target: 4000 kcal/person/day       │
│  3 days × 3 people × 4000 = 36,000 kcal target                   │
│  Planned: 32,400 kcal  ━━━━━━━━━━━━━━━━━━━░░░  90% — short 3,600 │
│                                                                  │
│  [▼ Day 1 — Friday 2026-07-10]              1,140 / 12,000 kcal  │
│      Dinner                                                      │
│        | Mountain House Lasagna ▼ | 2 | 570 | Tom ▼ | × |        │
│        + add item                                                │
│      + add meal (breakfast / lunch / snack)                      │
│                                                                  │
│  [▶ Day 2 — Saturday 2026-07-11]            collapsed            │
│  [▶ Day 3 — Sunday 2026-07-12]              collapsed            │
│                                                        [ Save ]  │
└──────────────────────────────────────────────────────────────────┘
```

**Behaviour:**
- Day cards auto-generated from trip's `start_date`/`end_date`. **Collapsed by default**, with the day's totals visible on the collapsed bar.
- Activity-level dropdown sets `kcal_per_person_per_day` to the matching default; a small input next to it allows per-trip override.
- Target/planned bar: green at 95-110% of target, amber outside.
- Add meal: dropdown picks `breakfast | lunch | dinner | snack`. Multiple of the same name allowed.
- Item rows:
    - **Food** — autocomplete combobox sourced from `foods.json`. Type to filter; pick from list; if the typed name is not in the catalog, an inline option `+ Create '{name}' as new food` appears. Picking it opens a **modal overlay** with the foods edit form (stays in trip flow), with the `name` field pre-filled to the typed text and the other fields blank. On save, the modal POSTs to `/api/foods`, then the autocomplete closes with the new food selected.
    - **Servings** — integer input.
    - **kcal** — read-only, computed `servings × kcal_per_serving`. Shows `?` + warning tag if `food_id` is missing from catalog.
    - **Who** — dropdown of trip participants (from `trip.md` frontmatter) + "shared".
    - **× remove** drops the row.
- **Save** — single button at bottom; POSTs the whole plan to `/api/trip/{slug}/meals`. Server regenerates the markdown body and rewrites `food.md` atomically.
- Drag-reorder: out of scope for v1.
- Read-only fallback: if JS is disabled, the rendered markdown body is shown (same content the editor wrote on the most recent save). For trips that have never been saved through the new UI, the body is whatever was already in `food.md` (typically the template placeholder or the legacy prose).

## Migration of existing trips

Two existing trips have prose-only `food.md` (no frontmatter): `killarney-2026-05`, `killbear-2026-08`.

**Approach: no automatic data migration.** The new code treats a `food.md` with no frontmatter as "no plan yet" and renders an empty meal planner with day cards ready for entry.

**Mitigation:** whenever the user opens the meal planner for a trip whose `food.md` has non-empty body and no frontmatter, show a banner at the top of the section:

> *This trip has notes in `food.md` that aren't in the new structured format. Saving will replace them — copy anything you want to keep first.* `[ View raw ]`

The "View raw" link displays the existing markdown in a modal so the user can copy it. The banner stops appearing once frontmatter exists (i.e. after the first save). No persistent dismiss flag — the condition is purely a function of the file's current state.

## Seed `foods.json`

Ship with ~10–20 common items so the catalog isn't empty on first run. Categories `meal`, `snack`, `drink`, `condiment`, `other`. Includes:

- Freeze-dried meals: Mountain House Lasagna, Backpacker's Pantry Pad Thai, Mountain House Beef Stew
- Dry goods: instant mashed potatoes, instant oatmeal packet, instant rice
- Snacks: Clif Bar (chocolate chip), GORP, peanut butter (single-serve)
- Protein: tuna pouch, canned chicken
- Drinks: instant coffee packet, hot chocolate packet
- Other: olive oil (small bottle)

Approximate kcal/serving values entered by hand from product labels. User edits/adds from there.

## File-write safety

- `foods.json` writes are atomic: write `foods.json.tmp`, then `os.replace(tmp, foods.json)`.
- `food.md` writes the same way.
- `foods.json.load_catalog()` checks file mtime against the cached value on each call; reloads if changed.
- `version` field on `foods.json` is checked on load; unknown version aborts startup with a clear error.

## Testing

| Test file | Coverage |
|---|---|
| `test_foods_service.py` | load/save/upsert/delete; slug collision handling; mtime cache invalidation; `find_references` |
| `test_meal_plan_service.py` | frontmatter round-trip; `compute_totals` math; markdown body rendering; missing-`food_id` soft-fail; default activity → kcal; participant resolution from `trip.md` |
| `test_foods_routes.py` | happy-path CRUD; validation errors; delete blocks/forces with refs |
| `test_meal_plan_integration.py` | empty trip plan → save → reload via `/api/trip/{slug}` → assert section rendered correctly |

All tests use a tmp `foods.json` and `trips/` directory (existing test conftest pattern). No new external mocks.

## Risks & known gaps

- **Body regeneration loses prose under headings.** Acceptable; documented in the file-head comment + first-load banner.
- **`id` is a slug from the *first* `name`.** If the user renames "Tuna Pouch" → "Sardines in Oil", the id `tuna-pouch` becomes a misnomer but still works. Users can delete + re-create if they care; meal plans referencing the old id would need manual updating in that case (warning surfaced).
- **No multi-user concurrent editing of `foods.json`.** Single-user app.
- **Single uvicorn worker assumed.** In-memory catalog cache is per-process; cross-worker invalidation not implemented.

## Out-of-scope (deferred)

- Pack weight per food.
- Price / cost-split.
- Macro split.
- GPX-derived calorie estimates.
- Reminders / shopping list export.
- Sharing or syncing the catalog across machines.
- Drag-reorder of meal/item rows.
