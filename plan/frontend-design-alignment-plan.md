# Align frontend/ visual design with the rebuilt marketing site

## Context

The marketing site (`marketing/`, Astro) was just rebuilt with a "bold & editorial" visual
language: a near-monochrome ink/paper palette with one "recording red" accent, Fraunces (a
high-contrast serif) for display headlines, IBM Plex Mono for labels/numbers, sharp corners
everywhere (no border-radius), and thick borders/rules in place of soft box-shadows. The user wants
the logged-in product app (`frontend/`, Next.js 16 / React 19 / Tailwind v4) restyled to match, so
the whole product feels like one brand instead of two.

Scoping confirmed: colors/fonts are centralized in one file (`frontend/app/globals.css`), so the
palette/font swap itself is small. The real cost is that **there is no shared Button/Card/Badge
component library** — every page hand-rolls Tailwind classes inline, so the sharp-corners/no-shadow
visual language needs updating in ~21 files individually (84 `rounded-*` occurrences across 14
files, 22 `shadow-soft` occurrences across 9 files). Per user decision, this pass also **extracts
shared Button/Card/StatusBadge primitives** while touching every file anyway, and **adds dark
mode** to reach full parity with the marketing site (which already supports it). The one
already-red status-error convention (`text-red-600`, the `failed` status badge, etc.) stays a
**separate token** from the new brand accent, which is also red — so a failed-job badge is never
visually confused with a primary CTA.

## Design tokens (`frontend/app/globals.css`)

Rewrite the token set to match the marketing site's naming and add dark-mode support (currently
this file has a comment stating dark mode was deliberately never added — that decision is being
reversed here):

```css
@import "tailwindcss";

:root {
  --paper: #ffffff;
  --paper-shade: #f2f0ec;
  --ink: #14120f;
  --ink-soft: #56514a;
  --line: #dedbd4;
  --accent: #c81e3a;
  --accent-ink: #ffffff;

  /* Separate from --accent on purpose -- a failed-job badge must never read as a CTA. */
  --status-success: #1f7a4d;
  --status-success-soft: #e4f2ea;
  --status-error: #b3141f;
  --status-error-soft: #fbe6e6;
  --status-warning: #9c631a;
  --status-warning-soft: #fbe9cf;
  --status-info: #2b3a67;
  --status-info-soft: #eef1f5;

  --shadow-soft: none; /* deprecated -- borders carry separation now, see below */
}

@media (prefers-color-scheme: dark) {
  :root {
    --paper: #121110;
    --paper-shade: #1c1a17;
    --ink: #f4f1ea;
    --ink-soft: #b6afa4;
    --line: #35312b;
    --accent: #ff6248;
    --accent-ink: #14120f;
    /* status-* dark variants, same approach as marketing's tokens.css */
  }
}
:root[data-theme='dark'] { /* same overrides, for a manual toggle if one gets added later */ }
:root[data-theme='light'] { /* explicit light overrides, mirrors marketing/src/styles/tokens.css */ }

@theme inline {
  --color-paper: var(--paper);
  --color-paper-shade: var(--paper-shade);
  --color-ink: var(--ink);
  --color-ink-soft: var(--ink-soft);
  --color-line: var(--line);
  --color-accent: var(--accent);
  --color-accent-ink: var(--accent-ink);
  --color-status-success: var(--status-success);
  --color-status-success-soft: var(--status-success-soft);
  --color-status-error: var(--status-error);
  --color-status-error-soft: var(--status-error-soft);
  --color-status-warning: var(--status-warning);
  --color-status-warning-soft: var(--status-warning-soft);
  --color-status-info: var(--status-info);
  --color-status-info-soft: var(--status-info-soft);

  --font-display: var(--font-fraunces);
  --font-mono: var(--font-plex-mono);
  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
}

body {
  background: var(--paper);
  color: var(--ink);
  font-family: var(--font-sans);
}
```

Notes:
- `--background`/`--foreground`/`--surface`/`--muted`/`--brand-navy`/`--brand-amber`/`--brand-border`
  are retired in favor of `--paper`/`--ink`/`--line`/`--accent` etc., matching
  `marketing/src/styles/tokens.css`'s names exactly — this is what makes the two codebases feel
  like one system, not just visually similar. Every `bg-brand-navy`/`text-muted`/`border-brand-border`
  etc. across the ~21 files gets renamed to the new utility (`bg-ink`, `text-ink-soft`,
  `border-line`) as part of this pass.
- `--surface` (pure white cards) vs `--background` (off-white page bg) — a two-layer look — is
  intentionally flattened to one `--paper` used for both, matching the marketing site's flat
  paper + border-separation language (`--paper-shade` remains for a recessed/secondary panel, same
  role it plays in `marketing/src/styles/tokens.css`).
- No new webfont needed for body copy — same choice as marketing (`--font-sans` stays a system
  stack). Fraunces/Plex Mono are for headings/labels only (see below).

## Fonts (`frontend/app/layout.tsx`)

Swap `Geist`/`Geist_Mono` for `Fraunces`/`IBM_Plex_Mono`, both available via `next/font/google`
(self-hosted automatically by Next.js's font pipeline, same mechanism already in place — this is a
~4-line change, not scattered):

```tsx
import { Fraunces, IBM_Plex_Mono } from "next/font/google";

const fraunces = Fraunces({ variable: "--font-fraunces", weight: ["600", "900"], subsets: ["latin"] });
const plexMono = IBM_Plex_Mono({ variable: "--font-plex-mono", weight: ["400", "500", "600"], subsets: ["latin"] });
```
...and use `${fraunces.variable} ${plexMono.variable}` in the `<html>` className instead of the
Geist ones. Apply `font-display` (Fraunces, weight 900) to page-title `h1`s (Admin, Dashboard,
etc.) and `font-mono` (Plex Mono) to the wordmark, monetary figures, API keys, and status
badges/timestamps — mirroring exactly how `marketing/` uses these two faces. Body copy and dense
table/list content stay in the system sans stack for readability at small sizes.

## Shared primitives (new, since every file needs touching anyway)

Three new files in `frontend/components/`, replacing repeated inline Tailwind patterns:

- **`Button.tsx`** — `variant="primary" | "secondary"`, matching `marketing`'s `.btn-primary`
  (mono font, uppercase, `border-2 border-ink`, sharp corners, ink→accent hover) /
  `.btn-secondary` (underlined text link). Replaces every hand-rolled button className string
  (Sidebar's collapse toggle, admin's "Make admin" toggle, FeedbackButton's submit, etc.).
- **`Card.tsx`** — replaces the repeated `rounded-2xl border border-brand-border bg-surface p-4
  shadow-soft` pattern (confirmed in `admin/page.tsx`, `dashboard/page.tsx`,
  `settings/billing/page.tsx`, `DocumentCard.tsx`, `TranscriptViewer.tsx`, `UserMenu.tsx`,
  `FeedbackButton.tsx`) with `border-2 border-line bg-paper p-4` — no radius, no shadow.
- **`StatusBadge.tsx`** — promotes the `StatusBadge` function already local to
  `app/(app)/dashboard/page.tsx:24-32` into a shared component, remapping its ad-hoc
  `bg-blue-100 text-blue-700` / `bg-green-100 text-green-700` / `bg-red-100 text-red-700` /
  `bg-brand-navy-soft text-brand-navy` styles onto the new formal `--status-info` / `--status-success`
  / `--status-error` / `--status-info` tokens — one place to maintain the status→color mapping
  instead of a local object plus copies of the same idea wherever else a job/document status
  renders (e.g. `documents/page.tsx`, `dashboard/jobs/[id]/page.tsx`).

`NavLink` (already a small local function inside `Sidebar.tsx`) stays where it is — it's
Sidebar-specific, not repeated elsewhere, so extracting it adds a file without reducing real
duplication.

## Rollout across the ~21 files

Same mechanical pass everywhere, in this order (chrome first — it's shared across every route, so
fixing it once has the biggest leverage):

1. `globals.css` + `layout.tsx` — tokens and fonts (above). Nothing else can be verified visually
   until this lands.
2. `components/Button.tsx`, `Card.tsx`, `StatusBadge.tsx` — the new primitives.
3. `components/Sidebar.tsx` + `components/TopBar.tsx` — the shell rendered on every `(app)` page.
   Swap `rounded-lg`/`bg-brand-*`/`border-brand-border` for the new tokens, no radius.
4. `components/UserMenu.tsx`, `DocumentCard.tsx`, `FeedbackButton.tsx`, `TranscriptViewer.tsx`,
   `Pagination.tsx` — adopt `Card`/`Button` where their existing markup matches those patterns.
5. The 10 page routes (`admin`, `dashboard`, `dashboard/jobs/[id]`, `documents`,
   `settings/{api-keys,billing,integrations}`, `login`) — replace inline card/button/badge
   patterns with the new primitives, replace remaining raw `bg-brand-*`/`rounded-*`/`shadow-soft`
   occurrences, replace `text-red-600` error-text instances with `text-status-error`.
6. `login/page.tsx` gets a pass too even though it's the one pre-auth page, so a first-time user's
   very first screen already looks like the same brand as the marketing site they arrived from.

For each file: remove `rounded-*` classes entirely (no radius = already square), replace
`shadow-soft` with `border-2 border-line` (or reuse `<Card>`), replace `bg-brand-*`/`text-brand-*`/
`border-brand-border`/`bg-surface`/`bg-background`/`text-muted` with the renamed equivalents
(`bg-ink`, `text-ink-soft`, `border-line`, `bg-paper`), and replace ad-hoc non-brand Tailwind colors
(`text-red-600`, `bg-teal-400`, etc.) with the matching `--status-*` token by semantic meaning
(preserve what each color currently signals — don't reassign meanings).

## Verification

1. `npm run build` in `frontend/` must succeed with no type errors (Tailwind v4 will fail loudly on
   a utility class referencing a `--color-*` token that no longer exists, which is a good forcing
   function for catching missed renames).
2. Visually check each of the 10 routes in both light and dark OS theme (`prefers-color-scheme`) —
   sidebar/topbar chrome, at least one page using `Card`, one using `Button`, and the dashboard's
   job list (all four `StatusBadge` states: queued/processing/done/failed).
3. Confirm the login page (pre-auth, no sidebar) also picked up the new fonts/palette.
4. Confirm a failed-job `StatusBadge` (status-error, a plain semantic red) and a primary `Button`
   (accent, the brand red) are visually distinguishable side by side — the whole reason the two
   reds were kept separate.
5. Grep `frontend/app` + `frontend/components` for `brand-navy`, `brand-amber`, `brand-border`,
   `bg-surface`, `bg-background`, `shadow-soft`, and `rounded-` — all should return zero matches
   when the pass is complete.
