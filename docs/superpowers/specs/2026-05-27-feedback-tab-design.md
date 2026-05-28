# Feedback Tab — Design

**Goal:** A nav-linked Feedback board where logged-in users post ideas or bug
reports — with their name, an optional attached image, and a status the group
can triage (Open / Planned / Done).

## Decisions (locked)
- **Images** stored inline in the database (bytea / BLOB), served by the app. No
  external storage or new secrets.
- **Moderation:** a user may delete only their own posts.
- **Status:** every post has `open | planned | done`; any logged-in user can change
  it (no admin role exists in the shared-password model).
- **Visibility:** the board is shared — all logged-in users see all posts, newest first.
- **Types:** `idea | bug` (plain text labels, no emoji). Compose placeholder: "What's up?".

## Data model
A `feedback` table (mirrors the existing `trips`/`checklist_state` dual-backend setup):

| column      | type                | notes                                  |
|-------------|---------------------|----------------------------------------|
| id          | text PK             | uuid4 hex, app-generated               |
| author      | text                | username (`current_user.id`)           |
| kind        | text                | `idea` \| `bug`                         |
| body        | text                | the message                            |
| status      | text                | `open` \| `planned` \| `done` (def open)|
| image       | bytea / BLOB        | nullable                               |
| image_mime  | text                | nullable                               |
| created_at  | double precision /  | unix epoch float (same type both       |
|             | REAL                | backends → uniform ordering/format)    |

- **Postgres:** added to `app/services/schema.sql` (+ `enable row level security`,
  matching the other tables). Created at boot by `pg.ensure_schema()`.
- **SQLite (local/tests):** created by a new `_ensure_feedback()` in `db.init_schema()`.

## Storage service — `app/services/feedback.py`
Pure CRUD branching on `config.STORAGE_BACKEND` (postgres → `pg.connection()`,
else → `db.connect()`), returning a `FeedbackPost` dataclass
(`id, author, kind, body, status, created_at, has_image`):
- `create(author, kind, body, image=None, image_mime=None) -> id` — validates kind/body/size
- `list_all() -> [FeedbackPost]` — newest first, no image bytes
- `get(id) -> FeedbackPost | None`
- `get_image(id) -> (bytes, mime) | None`
- `set_status(id, status)` — validates status
- `delete(id)`
- Constants: `KINDS`, `STATUSES`, `MAX_IMAGE_BYTES = 5 MiB`; `FeedbackError(ValueError)`.

## Routes — `app/routes/feedback.py` (all behind `require_user`)
- `GET  /feedback` — render board (compose box + posts)
- `POST /feedback` — create (multipart: `kind`, `body`, optional `image`); author = current user
- `POST /feedback/{id}/status` — set status (any user)
- `POST /feedback/{id}/delete` — author-only (403 otherwise)
- `GET  /feedback/{id}/image` — serve image bytes (404 if none)

Registered in `app/main.py`. Image upload validated: must be `image/*`, ≤ 5 MiB.

## UI
- `app/templates/feedback.html` extends `base.html`, includes `partials/nav_band.html`.
- Compose card: Idea/Bug toggle, textarea ("What's up?"), optional image attach, Post.
- Posts newest-first: author, type label, relative time (`reltime` Jinja filter), status
  `<select>` (auto-submits), body (autoescaped, `pre-wrap`), image thumbnail linking to full
  image, and a delete control shown only on the viewer's own posts.
- A **Feedback** link added to `partials/nav_band.html` so it appears app-wide.

## Testing — `tests/test_feedback.py`
- Unit (sqlite tmp via monkeypatched `db.DATABASE_PATH` + `init_schema`): create/list/get/
  delete/set_status/get_image; invalid kind, empty body, oversized image raise `FeedbackError`.
- Route (TestClient, `AUTH_ENABLED`, two users via signed cookies): create (with/without image),
  newest-first ordering, status change, delete own (redirect) vs other's (403), image round-trip,
  invalid kind 400, non-image / oversized upload 400, anonymous 401.

## Out of scope (YAGNI)
Replies/threads on feedback items, upvotes, edit-after-post, email notifications.
