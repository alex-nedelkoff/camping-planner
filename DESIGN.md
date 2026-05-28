# Camping Planner — Design System

Tokens are the source of truth in `app/static/css/index.css` (`:root`). This file
documents them for design work.

## Color (field-journal palette)
Warm parchment surfaces, ink-green text, earthy accents. Never pure #000/#fff.

| Token              | Value      | Role |
|--------------------|------------|------|
| `--ink`            | `#1f2a23`  | primary text (deep green-black) |
| `--ink-soft`       | `#4a5d4f`  | secondary text |
| `--ink-faint`      | `#8a8a78`  | muted labels, placeholders |
| `--rule`           | `#cbbf9f`  | borders / hairlines |
| `--rule-soft`      | `#e1d6b8`  | softer borders |
| `--parchment`      | `#f5efe1`  | page background |
| `--parchment-deep` | `#ece2c9`  | inset / secondary surface |
| `--parchment-mist` | `#fbf6e6`  | raised surface (panels) |
| `--rust`           | `#a8451f`  | primary accent / CTA |
| `--rust-bright`    | `#c66633`  | hover accent |
| `--slate`          | `#3a5666`  | cool accent (water, map) |
| `--moss`           | `#4f6644`  | green accent (terrain) |

Strategy: **Restrained** in the product (parchment + ink + one rust accent).
The splash leans **Committed** — earth tones carry the surface, rust commits the CTA.

## Typography
- `--font-serif` **Fraunces** — display / wordmarks / headings.
- `--font-sans` **DM Sans** — body and UI.
- `--font-mono` **JetBrains Mono** — small tracked labels, kickers, coordinates, data.

Identity-locked: these fonts are the brand and are kept even though Fraunces/DM Sans
are otherwise common; preservation beats novelty here. Hierarchy via scale + weight,
≥1.25 ratio; headings use `clamp()`.

## Elevation
Soft, low shadows tinted toward ink: `--shadow` for resting cards; deeper
`0 24px 60px -28px rgba(31,42,35,.5)` for floating panels (login). No glassmorphism.

## Components
- **nav_band** (`partials/nav_band.html`) — top bar: home, trip dropdown, Feedback link, user pill / log out.
- **cards** — used for trips and feedback posts; full borders, never side-stripes, never nested.
- **buttons** — `.btn` (rust), `.btn-ghost` (text). Login uses `.splash__btn`.
- **login splash** (`login.html` + `login.css`) — full-viewport SVG topographic scene
  (contours, a dashed route to a map pin) with the form in a parchment map-panel.

## Motion
Ease-out (quint/expo) only, no bounce. Entrance reveals (panel rise, pin drop,
route fade) gated behind `prefers-reduced-motion`. Never animate layout properties.
