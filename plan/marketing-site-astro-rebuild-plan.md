# Rebuild the marketing site: Astro + Starlight, full visual revamp

## Context

The marketing site is currently plain static HTML/CSS/JS at the repo root (`index.html`, `api.html`, `styles.css`, `game.js`), deployed to Netlify with zero build step. The user wants to add a blog, developer docs, and animations, and asked whether a framework rewrite makes sense. After walking through the tradeoffs together, the decisions landed on:

- **Astro** as the framework — content collections + MDX for the blog, near-zero JS by default, full creative control over markup/CSS for the hand-built marketing pages.
- **Starlight** (Astro's official docs theme) scoped to just the new `/docs` section — gives sidebar nav + Pagefind static search (no server, no database, index built at deploy time) for free, without forcing the whole site into a docs-site template.
- Deploy stays **fully independent from `frontend/`** — same spirit as today (a static build, deployed via Netlify). `frontend/`'s Next.js/Docker product app is untouched.
- **Full visual revamp**, not a faithful port — direction: **"Bold & editorial"** (high contrast, expressive/large type, more magazine-like and distinctive than the current friendly cream/navy/amber SaaS look).
- The existing "Spot the Slide" game carries forward as an interactive homepage element (it's a deliberate product-relevant touch — dramatizes "smart frame capture" — not filler), redesigned visually but keeping its mechanic.

This plan covers the technical rebuild. It does **not** pin down actual color/type values for the redesign — that's a design-approval checkpoint early in the build (step 2 below), separate from this architecture.

## Repository layout

New top-level directory: **`marketing/`**, sibling to `backend/`, `frontend/`, `baseten/`, `deploy/`, `local_test/`, `plan/`, `validation/` — matching this repo's existing convention of one directory per deployable unit, each with its own README. (`README.md` currently describes the marketing site as `index.html`/`styles.css`/`script.js`/`thanks.html` — already stale, since `script.js`/`thanks.html` don't exist anymore and `api.html`/`game.js` aren't mentioned. This section needs updating regardless of this rebuild.)

Cutover sequencing (two commits, not one):
1. Build `marketing/` fully, verify via a Netlify deploy preview pointed at it, production DNS/live site untouched.
2. Once confirmed working, a small follow-up commit deletes the old root `index.html`, `api.html`, `styles.css`, `game.js`, `images/`, flips `netlify.toml`, and updates `README.md`'s "Repo layout" and "Local development"/"Deployment" sections. Git history preserves the old files if ever needed (`git log --follow`); no `archive/` copy is warranted.

## Astro project structure

```
marketing/
├── package.json
├── astro.config.mjs
├── netlify.toml                 # see "Deploy config changes" — actually lives at repo root, not here
├── public/                      # favicon, og-default.png, robots.txt, brand images
├── src/
│   ├── content.config.ts        # collection schemas (blog + docs)
│   ├── content/
│   │   ├── blog/                # *.mdx posts
│   │   └── docs/                # Starlight's required collection name/location
│   ├── layouts/
│   │   ├── BaseLayout.astro     # <head>, meta/OG/schema.org, analytics, tokens.css
│   │   ├── MarketingLayout.astro
│   │   └── BlogPostLayout.astro
│   ├── components/
│   │   ├── Header.astro
│   │   ├── Footer.astro
│   │   ├── Hero.astro
│   │   ├── WhatsNewGrid.astro
│   │   ├── FeatureGrid.astro
│   │   ├── PricingTable.astro
│   │   ├── EnterpriseCta.astro
│   │   ├── FinalCta.astro
│   │   ├── Reveal.astro         # scroll-reveal wrapper
│   │   └── SpotTheSlide/
│   │       ├── SpotTheSlide.astro
│   │       ├── spot-the-slide.ts    # ported game.js logic
│   │       └── spot-the-slide.css
│   ├── pages/
│   │   ├── index.astro
│   │   └── blog/
│   │       ├── index.astro
│   │       ├── [slug].astro
│   │       └── rss.xml.ts
│   ├── scripts/
│   │   └── reveal.ts            # shared IntersectionObserver for scroll reveals
│   └── styles/
│       ├── tokens.css           # design tokens (values TBD at design checkpoint)
│       ├── base.css             # resets, type scale, container
│       ├── motion.css           # reveal keyframes + prefers-reduced-motion guards
│       └── starlight-overrides.css
└── (docs pages render from src/content/docs/**, no src/pages/docs/* — would collide)
```

Scaffold with `npx create-astro@latest marketing` (TypeScript strict) rather than hand-authoring config from scratch, then add dependencies:

```json
{
  "dependencies": {
    "astro": "^7.1.5",
    "@astrojs/starlight": "^0.41.5",
    "@astrojs/mdx": "^7.0.5",
    "@astrojs/sitemap": "^3.7.3",
    "@astrojs/rss": "^4.0.19",
    "sharp": "^0.35.3"
  }
}
```

### Content collection schemas (`src/content.config.ts`)

```ts
import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';
import { docsLoader } from '@astrojs/starlight/loaders';
import { docsSchema } from '@astrojs/starlight/schema';

const blog = defineCollection({
  loader: glob({ pattern: '**/*.mdx', base: './src/content/blog' }),
  schema: ({ image }) => z.object({
    title: z.string(),
    description: z.string().max(160),
    publishDate: z.coerce.date(),
    updatedDate: z.coerce.date().optional(),
    author: z.string().default('Framewrite'),
    tags: z.array(z.string()).default([]),
    heroImage: image().optional(),
    heroImageAlt: z.string().optional(),
    draft: z.boolean().default(false),
  }),
});

const docs = defineCollection({ loader: docsLoader(), schema: docsSchema() });

export const collections = { blog, docs };
```

The `docs` collection **must** use Starlight's own `docsLoader()`/`docsSchema()` — that's how the integration hooks in; a hand-defined schema here is the most common way this setup breaks.

### Scoping Starlight to `/docs` inside one larger site

Starlight ships as an Astro *integration*, not a whole-site template — it only looks like a full site in tutorials because it's often the only integration registered. Register both it and MDX/sitemap on the same project in `astro.config.mjs`:

```js
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import mdx from '@astrojs/mdx';
import sitemap from '@astrojs/sitemap';

export default defineConfig({
  site: 'https://framewrite.cc',
  integrations: [
    mdx(),
    starlight({
      title: 'Framewrite Docs',
      description: 'API reference for the Framewrite conversion API.',
      customCss: ['./src/styles/tokens.css', './src/styles/starlight-overrides.css'],
      sidebar: [
        {
          label: 'API Reference',
          items: [
            { label: 'Getting Started', slug: 'docs/getting-started' },
            { label: 'Authentication', slug: 'docs/authentication' },
            { label: 'Submit a Job', slug: 'docs/submit-a-job' },
            { label: 'Check Status & Get Results', slug: 'docs/check-status-and-results' },
          ],
        },
      ],
    }),
    sitemap(),
  ],
});
```

Starlight mounts its pages at `/docs/...` automatically because the collection it reads is literally named `docs` (`src/content/docs/`) — each page's route derives from the file path relative to that folder (`getting-started.mdx` → `/docs/getting-started`). Everything else (`/`, `/blog`, `/blog/[slug]`) is plain `.astro` under `src/pages/`, untouched by Starlight, as long as `src/pages/docs/` is never created (that would collide). Pagefind's search index builds automatically as part of `astro build` — no extra deploy config, no server.

## Design system approach (mechanism, not values)

`src/styles/tokens.css` is the single source of truth — semantic CSS custom properties (`--color-bg`, `--color-accent`, `--font-display`, `--step-0`...`--step-6` fluid type scale, `--space-1`...`--space-9`, `--ease-out`/`--duration-*`), scoped to `:root` and overridden under `:root[data-theme='dark']`. This directly replaces today's flat `styles.css:1-15` block (`--canvas`/`--navy`/`--accent`), reorganized into semantic names so a future palette swap is a find-and-replace of *values*, never *usages*.

- `BaseLayout.astro` imports `tokens.css`/`base.css`/`motion.css` once; every page gets them for free.
- Components use scoped `<style>` blocks referencing `var(--color-accent)` etc. — never hardcode a value locally. State this convention explicitly in `marketing/README.md`.
- **Starlight theming**: `customCss` (already wired above) loads `tokens.css` then `starlight-overrides.css`, which remaps Starlight's own variables onto the shared tokens:

```css
/* src/styles/starlight-overrides.css */
:root {
  --sl-color-accent: var(--color-accent);
  --sl-color-bg: var(--color-bg);
  --sl-color-bg-nav: var(--color-surface);
  --sl-color-text: var(--color-text);
  --sl-font: var(--font-body);
}
```

This is Starlight's documented "reskin to match a parent site" pattern — avoids docs looking like a stock template or maintaining a second, drifting palette.

## Animation approach

**Plain CSS transitions/keyframes + one shared `IntersectionObserver` script — no animation library.** This is exactly the pattern the codebase already uses (`game.js`'s `prefers-reduced-motion` short-circuit, `styles.css`'s reduced-motion media blocks for the game's tile flash) — extend it, don't replace it with a new convention, and it keeps the "near-zero JS by default" property that motivated choosing Astro.

- `src/styles/motion.css`:
```css
[data-reveal] { opacity: 0; transform: translateY(12px); }
[data-reveal].is-visible {
  opacity: 1; transform: none;
  transition: opacity var(--duration-base) var(--ease-out), transform var(--duration-base) var(--ease-out);
}
@media (prefers-reduced-motion: reduce) {
  [data-reveal] { opacity: 1; transform: none; transition: none; }
}
```
- `src/scripts/reveal.ts`: one shared `IntersectionObserver`, toggles `.is-visible` on `[data-reveal]` elements, early-returns if `matchMedia('(prefers-reduced-motion: reduce)').matches`. Loaded once from `BaseLayout.astro`'s `<head>` (a plain module script, no hydration directive needed — it's page behavior, not a component).
- `Reveal.astro` is a thin `<div data-reveal><slot /></div>` wrapper section components opt into.
- Hero stagger (H1/subhead/CTA entrance) reuses the same primitive via a per-element `style="--reveal-delay: 80ms"` + `transition-delay: var(--reveal-delay)` — no per-element JS.
- The **only** component needing a `client:*` hydration directive is `SpotTheSlide.astro`, because it's genuinely stateful interactive UI, not a scroll effect.

## Migrating "Spot the Slide"

**Keep it vanilla JS, wrapped as a plain `<script>` inside the Astro component — do not port to React/Vue.** It has no shared state with the rest of the page, no server data, and is already correct, accessible (`aria-live`, focus management on `#game-again`), and reduced-motion-aware. Introducing a UI framework here would mean shipping that framework's runtime for one widget — exactly what Astro's islands model is meant to avoid for a component that doesn't need it.

- `SpotTheSlide.astro`: the `.game-idle`/`.game-play-area`/`.game-end` markup, restyled to the new tokens.
- `spot-the-slide.ts`: `game.js`'s logic ported near-verbatim (state object, `roundDuration`, `startRound`, `onCorrect`/`onWrong`/`onTimeout`, `localStorage` best score, GA4 `trackEvent` calls) — only the tile visuals (`SLIDE_MARKUP`, noise-variant CSS) change, to match the new bold/editorial look. The GA4 events already wired (`spot_the_slide_start`/`_end`/`_cta_click`) must keep firing under the new build — verify in the polish pass.
- Only one instance ever exists per page, so the existing bare `document.getElementById` lookups don't need scoping/query-selector rework.

## Docs content migration

Maps `api.html`'s existing (accurate) 3-step content into 4 focused Starlight pages instead of one long scroll:

- **`/docs`** (`index.mdx`) — the pitch + quick-start snippet + links to the pages below, pulled from `api.html`'s intro copy.
- **`/docs/getting-started`** — base URL (`https://api.framewrite.cc`), where to get an API key (Settings → API Keys), pricing cross-link, a minimal end-to-end curl example.
- **`/docs/authentication`** — `X-API-Key` header, key-safety note ("shown once"), error shape for missing/invalid key: **confirmed** via `backend/app/deps.py` — `HTTPException(401, "Missing credentials")` / `HTTPException(401, "Invalid or expired session token")` / `HTTPException(401, "Invalid or revoked API key")`, serialized by FastAPI as `{"detail": "..."}`.
- **`/docs/submit-a-job`** — `POST /api/convert_to_doc` (field `video`) and `POST /api/transcribe_audio` (field `audio`), both returning `202 {"job_id": "...", "status": "queued"}`. Use Starlight's `<Tabs>`/`<TabItem>` MDX components for the video-vs-audio examples.
- **`/docs/check-status-and-results`** — `GET /api/get_status?job_id=...`. Response fields **confirmed** via `backend/app/routes/status.py`'s `build_job_response`: `job_id`, `status` (`queued`/`processing`/`done`/`failed`, per `backend/app/models.py`'s `Job.status` comment), `progress_stage`, `job_type`, `title`, timestamps, `duration_seconds`, `billed_cents`; when `done`: `document_url`, `document_bundle_url`, plus `document_docx_url`/`document_pdf_url`/`document_transcript_json_url` when those exports exist; when `failed`: `error`. No further backend verification needed — this is already fully grounded in the actual route.

Sidebar order (auth → submit → poll) matches natural reading sequence, set directly in `astro.config.mjs`'s `sidebar` array (order = array order). The enterprise cross-link from `api.html`'s outro ("Converting a large video library?") becomes a callout at the bottom of `/docs/index.mdx` linking to `/#enterprise`.

## Blog content migration (greenfield)

Schema is in `content.config.ts` above. Two placeholder posts (structure only, no real marketing copy — that's a separate writing task):
- `welcome-to-the-framewrite-blog.mdx` — `draft: true`, announcement-post shape.
- `how-speaker-diarization-works.mdx` — `draft: true`, product-education shape (expands on the diarization feature already teased in the homepage's "what's new" section).

`src/pages/blog/index.astro` sorts by `publishDate` desc, filters `draft`, reuses the same card visual primitive as the feature/what's-new grids. `[slug].astro` uses `getStaticPaths()` over the collection. `rss.xml.ts` uses `@astrojs/rss`, same `!draft` filter.

## Deploy config changes

Stay on Netlify (first-class Astro support, no reason to move to Vercel). Two changes:

**Repo-root `netlify.toml`** (was `[build] publish = "."`):
```toml
[build]
  base = "marketing"
  publish = "dist"
  command = "npm run build"

[build.environment]
  NODE_VERSION = "22"

[[redirects]]
  from = "/index.html"
  to = "/"
  status = 301

[[redirects]]
  from = "/api.html"
  to = "/docs"
  status = 301
```
`base = "marketing"` is Netlify's standard monorepo pattern — scopes the build to the subdirectory without touching `frontend/`'s separate Docker/Fabric deploy at all. The redirects preserve any bookmarked/indexed links to the old `.html` paths.

**`marketing/package.json`** — standard `dev`/`build`/`preview` scripts (shown above under dependencies).

## Phasing (build order)

Each step is its own reviewable unit; step 2 is the one hard blocking gate (everything after commits to whatever's approved there).

1. **Scaffold** — `create-astro@latest marketing`, add MDX/sitemap, wire the `blog` schema only. Empty homepage running locally via `npm run dev`. No design work yet.
2. **Design tokens + direction checkpoint** — build `tokens.css`/`base.css` structure (placeholder values), then produce an Artifact mockup of the homepage hero + one feature section against the "bold & editorial" brief for actual color/type approval. **Stop here for sign-off.**
3. **Homepage** — `Header`/`Footer`/`Hero`/`WhatsNewGrid`/`FeatureGrid`/`PricingTable`/`EnterpriseCta`/`FinalCta` against approved tokens, porting copy verbatim from the current `index.html` (copy isn't part of the visual revamp). `SpotTheSlide` ships as static idle-panel markup only — logic comes in step 6.
4. **Blog** — listing, post template, RSS, the two placeholder posts. Independent of docs/game; can run in parallel with step 5.
5. **Docs/Starlight** — add the integration, wire `docsLoader`/`docsSchema`, write the 4 pages + index, apply `starlight-overrides.css`. Verify Pagefind search via `astro build && astro preview` (it doesn't activate under plain `astro dev`).
6. **Game migration** — port `game.js` → `spot-the-slide.ts`, redesign tile visuals to the approved direction, wire into the island from step 3.
7. **Animations** — `motion.css` + `reveal.ts`, sprinkle `data-reveal` across sections built in 3-4; verify reduced-motion behavior via DevTools emulation.
8. **Deploy cutover** — `marketing/package.json` build script, flip root `netlify.toml`, verify via a Netlify deploy-preview branch with production DNS untouched; only then merge the commit deleting the old root files and updating `README.md`.
9. **Polish** — sitemap/OG/robots.txt, Lighthouse/accessibility pass, and an analytics parity check confirming the existing GA4 events (`spot_the_slide_start`/`_end`/`_cta_click`) still fire under the new build.

## Verification

- After step 1: `npm run dev` in `marketing/` serves a page with no console errors.
- After step 5: `npm run build && npm run preview`, confirm `/docs`, `/docs/getting-started`, etc. render with sidebar nav and that the search box returns results.
- After step 6: play through the game (win/lose/timeout/play-again) exactly as previously verified for the vanilla version, plus confirm `localStorage` best-score persists and GA4 events fire (check the Network tab for `gtag`/`collect` requests, or GA4 DebugView).
- After step 7: toggle DevTools' "Emulate CSS prefers-reduced-motion: reduce" and confirm reveals render instantly with no motion.
- After step 8: hit the Netlify deploy-preview URL for `/`, `/blog`, `/docs`, and the two redirected legacy paths (`/index.html`, `/api.html`) before touching production DNS/the real `netlify.toml` merge.
- Full `npm run build` must succeed with zero errors/warnings as the final gate before cutover.
