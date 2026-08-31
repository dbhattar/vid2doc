# UI redesign — bold, colorful, modern SaaS direction

## Context

Framewrite's marketing site and app currently share one deliberate design
system: a "bold & editorial" look (per `marketing/src/styles/tokens.css`'s
own header comment) — warm off-black ink on warm off-white paper, exactly
one accent color (a "recording red," `#c81e3a`) used sparingly, sharp
0-radius corners everywhere, zero shadows ("rules/borders carry separation,
not soft shadows"), and a serif-display/mono-label type pairing (Fraunces +
IBM Plex Mono). It's a coherent, well-executed system — but the user has
found that it reads as print/editorial rather than as a SaaS product, and
doesn't communicate "what this app does" quickly enough. They want a full
visual overhaul, across both the marketing site and the signed-in app,
toward a bold/colorful/energetic modern-SaaS feel (Notion/Framer/Attio/
Cal.com register).

Worth knowing going in: the app's `Card.tsx` comment shows the team already
had a softer, rounded, shadowed look once (`rounded-2xl border ...
shadow-soft`) and deliberately moved away from it toward the current sharp
aesthetic. This redesign reverses that earlier call — a legitimate thing to
do, just not a "first time going this direction" situation.

Both properties already use the same token-naming convention
(`--paper`/`--ink`/`--accent`/`--line`, etc.) independently duplicated in
`marketing/src/styles/tokens.css` and `frontend/app/globals.css` — there's
no shared package, so both files need to be updated in lockstep and kept
that way; that duplication is a pre-existing pattern this plan keeps rather
than restructures (introducing a shared tokens package is a possible future
improvement, out of scope here).

## Direction (decided with the user)

- **Brand color**: retire the crimson/red as primary. New anchor is an
  **indigo/violet** (`#5B4FE9` light-mode accent, `#9C90FF` dark-mode
  accent) — closer to Linear/Attio territory, reads as confident modern
  SaaS. A warm **coral secondary** (`#FF6B4A` light, `#FF8A6B` dark) stays
  as a complementary energy color for gradients, secondary CTAs, and
  highlights — this is also where a thread of the old brand color survives,
  just demoted from "the one accent" to "the warm counterpart."
- **Neutrals shift cooler** to harmonize with an indigo primary (the
  current neutrals have a warm brown-black undertone that would clash):
  ink `#14131A`, ink-soft `#5B5A66` (light mode); paper `#FFFFFF`,
  paper-shade `#F1F0F7`, line `#E4E3ED`. Dark mode: paper `#121016`,
  paper-shade `#1C1A24`, ink `#F4F3F8`, ink-soft `#A7A5B4`, line `#322F3D`.
- **Typography**: swap Fraunces (serif display) for a bold geometric
  display sans — **Cabinet Grotesk** (Fontshare, free/self-hostable —
  confirm license terms at implementation time) — for headlines, paired
  with **Inter** for body copy and UI text. IBM Plex Mono stays, but its
  *role* narrows: no longer the default "voice" for every button/label/
  eyebrow (that moves to Inter); mono is reserved for genuinely monospace
  content (timestamps, transcript mockups, API keys/code).
- **Shape**: fully rounded, soft everywhere — new radius scale
  (`--radius-sm: 8px`, `--radius-md: 12px`, `--radius-lg: 20px`,
  `--radius-full: 9999px`), replacing the current `--radius-sm: 0`. Borders
  thin out from the current 2px/3px black rules to 1px `--line`-colored
  borders, since shadows now carry visual separation instead.
- **Elevation**: introduce a shadow scale where none existed
  (`--shadow-sm`, `--shadow-md`, `--shadow-lg`, plus an indigo-tinted
  `--shadow-accent` glow for primary CTAs). Dark mode shadows lean more on
  a lighter border + subtle glow than a literal drop shadow, since
  dark-on-dark shadows read poorly.
- **Motion**: keep the existing `[data-reveal]` scroll-entrance pattern
  (marketing) but soften the easing toward a slight spring/overshoot for
  small elements (buttons/cards, not large text blocks); add a hover-lift
  micro-interaction (`translateY(-2px)` + shadow increase) to cards and
  buttons in both properties — a hallmark of this genre that the current
  system has none of (no shadow to "increase" today).
- **Icons**: keep the Lucide line-icon set (functional, consistent,
  low-cost to keep), but give them a soft rounded-chip background
  (accent-soft tint) on active/hover states instead of a bare color change
  — ties icons into the new rounded shape language.
- Speaker colors (`frontend/lib/speakerColors.ts`) stay as distinct stock
  hues rather than being forced into the new 2-color brand palette — that's
  a legitimate data-viz reason (speakers need to be visually distinguishable
  from each other, not brand-matched), just confirm the existing
  `rounded-full` avatar chips still look right against the new palette.

## Rollout plan (phased — verify visually after each phase before moving on)

**Phase 1 — Foundation (tokens + fonts, both projects in lockstep)**
- `marketing/src/styles/tokens.css`: rewrite every color (light + dark),
  add radius/shadow tokens, retune the motion easing var.
- `marketing/src/styles/base.css`: swap font-face imports — drop Fraunces,
  add self-hosted Cabinet Grotesk + Inter (keep IBM Plex Mono imports as-is).
- `frontend/app/globals.css`: mirror the same color/radius/shadow token
  rewrite; extend the existing `@theme inline` block so new tokens (radius,
  shadow) become real Tailwind utilities (`rounded-md`, `shadow-md`, etc.),
  matching how `bg-paper`/`text-ink` etc. already work today.
- `frontend/app/layout.tsx`: swap the `next/font/google` Fraunces import
  for Cabinet Grotesk via `next/font/local` (self-hosted, since Cabinet
  Grotesk isn't on Google Fonts) + add Inter via `next/font/google`
  (already there, standard). Update the CSS variable names the fonts are
  exposed under to match `globals.css`'s expectations.

**Phase 2 — Core/shared components (cascades broadly, so do these before the long tail)**
- App: `components/Button.tsx` (rounded corners, Inter instead of uppercase
  mono as the default label voice, indigo primary fill, hover-lift +
  shadow), `components/Card.tsx` (rounded + `--shadow-sm` instead of the
  2px border), `components/Sidebar.tsx` (rounded active-nav chip behind the
  icon+label, softer dividers), `components/TopBar.tsx`,
  `components/ThemeToggle.tsx`.
- Marketing: `components/Header.astro`, `components/Footer.astro` (these
  set the tone every page inherits); establish the new button/card visual
  pattern here since marketing doesn't have a single shared Button/Card
  component the way the app does — bespoke per-component CSS follows the
  same new radius/shadow/color values instead.

**Phase 3 — Page/section sweep**
- Marketing: `Hero.astro` (this sets the first impression — new type,
  colors, and the hero is the natural place for the gradient/motion polish
  in Phase 4 too), `FeatureGrid.astro` (rounded shadow-cards replacing the
  bordered-grid technique), `PricingTable.astro`, `FAQ.astro`,
  `Testimonials/`, `Newsletter/`, `FinalCta.astro`, `TrialUpload/`,
  `changelog.astro`, `blog/`, `privacy.astro`.
- App: every dashboard page (`dashboard/audio`, `dashboard/video`,
  `dashboard/video-gen`, `dashboard/live`, `dashboard/jobs/[id]`,
  `documents`, `settings/*`, `admin/*`), plus components that don't fully
  route through Button/Card (`TranscriptViewer.tsx`, `JobRow.tsx`,
  `ProgressStepper.tsx`, review/scene-review panels) — replace one-off
  `border-2 border-line` / sharp-corner className patterns with the new
  rounded/shadow idiom.

**Phase 4 — Polish (optional, do after the above lands and reads well)**
- A blurred gradient-orb/mesh backdrop behind the marketing Hero (a common,
  low-cost way to read as "colorful/energetic" without custom illustration).
- Broader hover-lift/motion polish once the base shadow system is in place
  everywhere.
- Consider whether FeatureGrid or other marketing sections benefit from
  small illustrative accents — not required, evaluate once the core
  palette/type change is visible.

## Risks / things to check during implementation

- **Contrast**: verify the new indigo-on-white, white-on-indigo, and coral
  combinations meet WCAG AA before finalizing — pick this during Phase 1,
  not after everything's built on top of it.
- **Dark mode isn't a mechanical invert** — every new token needs a
  deliberately-chosen dark variant (already sketched above for the core
  neutrals/accent, but shadow/glow treatment in particular needs real
  in-browser checking since it behaves differently in dark mode).
- **Two independently-duplicated token files** (marketing + app) must move
  together — treat Phase 1 as one unit of work across both, not two
  separate ones that could drift.
- **Font licensing**: confirm Cabinet Grotesk's license permits this use
  (Fontshare's fonts are generally free for commercial/self-hosted use, but
  confirm before shipping).

## Verification

- After Phase 1: run both dev servers (`marketing`: `astro dev
  --background` per its own AGENTS.md; `frontend`: local `npm run dev` or
  the Docker stack) and visually confirm the new tokens actually render —
  check light AND dark mode on at least one page per property before
  proceeding to Phase 2.
- After Phase 2: spot-check Button/Card in both light/dark mode across a
  couple of pages that use them (e.g. `dashboard/audio`, the marketing
  Hero's CTA) — this is the highest-leverage check since these components
  cascade everywhere.
- After Phase 3: full visual pass over every page in both properties,
  light and dark mode, at both mobile and desktop widths (several pages
  have explicit `@media (max-width: ...)` breakpoints already).
- Run `npm run build` (or `astro build`) for both projects at the end of
  each phase to catch any broken className/token references early, same as
  the verification approach used earlier in this session.
