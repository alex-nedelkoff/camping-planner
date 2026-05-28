# Cookbook — Recipe Repository — Design

> Reference doc written after the fact. Shipped as PR #13 (commit `b1953bd`).

## Goal
A site-wide **cookbook** at `/recipes` where logged-in users can browse, filter, view, add, and edit recipes for both **canoe** and **car-camping** trips. Sits alongside the per-trip `Food` table in `trip.html` (which is "who brings what for each meal") — the cookbook is the library of repeatable meals.

## Decisions (locked in brainstorming)
- **Standalone now, wire to trips later.** Phase 2 ("Add this recipe to a trip" button that creates meal slots in the trip Food table) is an explicit follow-on and not built here.
- **Structured ingredients** — list of `{qty, unit, name}` (not freeform Markdown) so quantities can be **scaled live by servings** and a future shopping list / trip importer is feasible.
- **Author edits or deletes their own** (consistent with Feedback / Comments). No wiki-style anyone-edit.
- **Visual direction:** list = **editorial index** (Direction B in the companion — dense one-line rows with a thumb + meta, reads like the index at the back of a cookbook). Detail = **single-column journal** (Direction B — kicker, big Fraunces title, rust rule, ingredient list with quantity column, Markdown steps; headlamp-friendly).

## Data
A `recipes` table (Postgres + SQLite via the dual-backend convention; **auto-creates on deploy**):

| column        | type                                                    | notes                                    |
|---------------|---------------------------------------------------------|------------------------------------------|
| id            | text PK                                                 | uuid4 hex                                |
| author        | text                                                    | `current_user.id`                        |
| name          | text                                                    | ≤ 120 chars                              |
| style         | text                                                    | enum: `canoe` / `car` / `both`           |
| meal          | text                                                    | enum: `breakfast` / `lunch` / `dinner` / `snack` |
| servings      | integer ≥ 1                                             | base servings for the recipe             |
| prep_minutes  | integer, nullable                                       |                                          |
| cook_minutes  | integer, nullable                                       |                                          |
| ingredients   | `jsonb` (Pg) / `TEXT` (SQLite) — list of `{qty,unit,name}` | `qty` parsed from `"1/2"` / decimals to float; empty rows dropped |
| steps         | text                                                    | Markdown                                 |
| prep_at_home  | text, nullable                                          | optional Markdown (renders as "At home")  |
| gear          | text, nullable                                          | freeform                                 |
| tags          | `jsonb` / `TEXT` — list of strings                      | lowercased, deduped                      |
| notes         | text, nullable                                          | Markdown                                 |
| image         | `bytea` / `BLOB`                                        | optional, ≤ 5 MiB, `image/*` only        |
| image_mime    | text, nullable                                          |                                          |
| created_at    | double precision / REAL                                 | unix epoch float                         |

Indexed on `style` and `meal` for filter queries. `STYLES`, `MEALS`, `MAX_IMAGE_BYTES` exported by `app/services/recipes.py`.

## Service (`app/services/recipes.py`)
- `parse_qty("1/2")` → `0.5`; `parse_qty("1.5")` → `1.5`; empty / garbage → `None`.
- `create` / `get` / `update` / `delete` / `get_image` / `list_recipes(style=, meal=, tag=, q=)`.
- Filters: `style` / `meal` / `q` (search name + ingredients via `lower(…) LIKE` / `ILIKE`) applied in SQL; **`tag` filtered in Python** (small dataset; avoids per-backend jsonb dance).
- Validation: `RecipeError` for empty name, bad style/meal, servings < 1, oversized image.

## Routes (`app/routes/recipes.py`, all `require_user`, server-rendered)
- `GET /recipes` — index with filter chips (style / meal / tag) + search input.
- `GET /recipes/new` · `POST /recipes` — create form (multipart, optional image).
- `GET /recipes/{id}` — detail page.
- `GET /recipes/{id}/edit` · `POST /recipes/{id}` — **author-only** (403 otherwise).
- `POST /recipes/{id}/delete` — author-only.
- `GET /recipes/{id}/image` — image bytes.
- `GET /recipes?tag=xxx` works for tag links from the detail page.

## UI
- `app/templates/recipes_index.html` — editorial list (thumb / name / meta / `→`), filter chips macroed for `style` / `meal` / dynamic `tag` list, search form.
- `app/templates/recipe_detail.html` — single-column journal: kicker, Fraunces title, rust rule, hero image (if present), Ingredients section with the live **−/+ servings stepper**, optional "At home" section, "At camp" / "Prep" section (Markdown), gear/tags/notes aside, edit/delete shown only to the author.
- `app/templates/recipe_form.html` — shared by new + edit. Dynamic ingredient table (`+ add row` / `× remove`), Markdown textareas, photo upload with `clear_image` checkbox on edit.
- `app/static/css/recipes.css` — scoped to `.cb` / `.rcp` / `.rcp-form`, uses existing tokens.
- `app/static/js/recipe_form.js` — adds/removes ingredient rows; never deletes the last row (clears it instead).
- `app/static/js/recipe_detail.js` — servings scaler. Each ingredient row carries `data-qty` + `data-unit`; multiplier = current / base. Verified math live: 4 → 6 = 1.5×, 6 → 2 = 0.5×.
- "Recipes" link added to `partials/nav_band.html` so it appears app-wide.

## Tests
16 tests in `tests/test_recipes.py` — `parse_qty`, storage round-trips, invalid enums, empty-name / oversized-image rejection, empty-row drop, filter combinations, update preserves author, image round-trip, delete, anonymous redirect, index renders + filters, create-via-form (with parsing), edit/delete authz (Jeff can't edit Alex's), image served through route.

## Out of scope (intentional)
- "Add this recipe to a trip" / cookbook ↔ trip Food integration (the planned next feature).
- LLM-driven extraction from external text (a separate handoff prompt covers a Reddit → Obsidian pipeline that could feed the cookbook later).
- Star ratings / "I've cooked this" markers / comments on recipes.
- Edit history / version diffs.
