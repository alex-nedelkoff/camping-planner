# Per-Trip Comment Bubble — Design

> Reference doc written after the fact. Shipped as PR #11 (commit `7550111`) with the minimize-fix PR #12 (`0f7da63`).

## Goal
A **minimizable chat bubble** docked bottom-right on every `/trip/{slug}` page. Logged-in users post comments with their name; comments persist per trip and load/post **without a page reload**.

## Decisions (locked in brainstorming)
- **Delete-your-own** moderation (consistent with Feedback).
- **No badge** on the minimized bubble — just the icon. (Total count was considered; unread-tracking was considered and rejected for scope.)
- **Anyone logged in can comment** on any trip.
- **Flat** — no threaded replies.
- Bubble **starts minimized**; open/closed state is remembered per device in `localStorage` under the global key `cp-comments-open`.

## Data
A `trip_comments` table (Postgres + SQLite via the dual-backend convention; **auto-creates on deploy**):

| column     | type                                 | notes                          |
|------------|--------------------------------------|--------------------------------|
| id         | text PK                              | uuid4 hex                      |
| trip_slug  | text                                 | indexed (`trip_comments_slug_idx`) |
| author     | text                                 | `current_user.id` (username)   |
| body       | text                                 | ≤ 2000 chars (`MAX_COMMENT_LEN`) |
| created_at | double precision / REAL              | unix epoch float               |

`app/services/comments.py` exposes `create / list_for (chronological asc) / get / delete`. `app/services/schema.sql` + `db.py:init_schema` create the table.

## API (`app/routes/comments.py`, prefix `/api`, all behind `require_user`)
- `GET /api/trips/{slug}/comments` — list (oldest-first; `_ensure_trip` validates slug exists)
- `POST /api/trips/{slug}/comments` — add (JSON `{body}`), returns the created item with `mine: true`
- `DELETE /api/trips/{slug}/comments/{id}` — **author-only** (403 otherwise, 404 if missing or wrong trip)

Each returned item carries a `mine: bool` flag (server-computed) so the client shows the delete control only on your own.

## UI
- `app/templates/partials/comments.html` — root markup + scoped `<style>` block (kept inline because it's small and self-contained).
- Wired into `app/templates/trip.html` after the `.trip-page` div; the script tag is added to the trip page's scripts block.
- The widget reads `document.body.dataset.tripSlug` (already set by `trip.html`).
- `app/static/js/comments.js` (~100 lines) handles open/close, fetch/render, delete, post, escape-via-textContent, reduced-motion-aware entrance animation. Relative timestamps computed client-side.
- Rust FAB (💬) bottom-right when minimized; parchment-mist panel when open with rust header.

## CSS specificity gotcha (the bug fix in PR #12)
The panel's hide state was originally driven by the HTML `hidden` attribute. The UA `[hidden] { display: none }` rule and `.cpc__panel { display: flex; … }` have the **same single-class specificity**, and the scoped stylesheet loads after the UA's, so `display: flex` won and the panel never hid on minimize. **Fix:** `.cpc__panel[hidden] { display: none; }` raises specificity to (0,2,0).

## Tests
10 tests in `tests/test_comments.py` — storage round-trips, validation (empty/too-long), filters by trip, route authz (anonymous 401, unknown trip 404, delete own → 303 / delete other's → 403), `mine` flag computed server-side.

## Out of scope (intentional)
- Replies / threads.
- Edit-after-post.
- Real-time updates (no websockets or polling; refresh on bubble re-open).
- Unread-since-last-visit tracking.
