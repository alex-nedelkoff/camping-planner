# Login Splash Redesign — Design (Direction C: Topographic Map)

> Reference doc written after the fact. Shipped as PR #10 (commit `8bbd04e`).

## Goal
Replace the unstyled `/login` page with a full-viewport **field-journal topographic-map scene** that doubles as the brand front door, while keeping the form behaviour (POST `/login`, `username` + `password`) untouched.

## Register & process
- **Register:** brand (design *is* the welcome). All other app pages remain product register.
- Built via the **`/impeccable`** skill's `craft` flow. Direction picked in the visual-companion brainstorm: **C — Topographic Map** (vs. A "Field Journal" and B "Dusk at Camp").
- Harness has no native image generation, so the approved mock from the companion was the visual contract.
- `PRODUCT.md` + `DESIGN.md` were added in the same PR so future impeccable runs are grounded.

## Identity preservation
- **Fonts kept** (Fraunces, DM Sans, JetBrains Mono) even though they are on impeccable's reflex-reject list — identity preservation wins for an established brand.
- Palette (parchment / ink-green / rust / moss / slate) used as-is from `index.css :root`.

## Composition
- Asymmetric — **not** a centered card.
- Crafted **SVG topographic scene** fills the viewport behind everything: nested contour rings around an upper-right "summit", a secondary lower-left rise, a faint slate lake, and a **dashed rust route line** drawing from a moss start-dot in the lower-left to a **teardrop pin** at the summit.
- A **parchment "map panel"** anchored lower-left holds the form: mono kicker "PLOT YOUR COURSE", Fraunces wordmark "Camping Planner", a short rust rule, tagline "Trips, gear, and routes, planned with your crew.", labelled name + password fields with visible focus rings, rust CTA "Log in", in-rust error message when wrong-password.
- Mono coordinate label top-right (`46.01° N / 81.41° W`), legend bottom-right (`N ↑  1:50 000`).

## Motion
- Reduced-motion-gated entrance: panel rises + pin drops + route fades on first paint. No CSS layout-property animation. Cubic-bezier ease-out (no bounce).

## Responsive
- Desktop: asymmetric scene with panel lower-left.
- Mobile (≤640px): map recedes to a quiet backdrop, panel goes full-width centered, coords/legend hidden.

## Files
- `app/templates/login.html` — full splash markup including the inline SVG scene + form.
- `app/static/css/login.css` — scoped styles, linked via `head_extra` (`?v={{ static_version }}`).
- `PRODUCT.md`, `DESIGN.md` — repo-root impeccable context.

## Out of scope (intentional)
- Per-user accounts / sign-up flow (the app uses one shared `SITE_PASSWORD` + free-text username; see [[camping-planner-deploy]]).
- Image-based hero (the SVG scene *is* the imagery; brand register explicitly allows generated SVG as imagery).
