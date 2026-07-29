# Framewrite marketing site

The public site at [framewrite.cc](https://framewrite.cc) — homepage, blog, and developer docs.
Built with [Astro](https://astro.build) + [Starlight](https://starlight.astro.build) for `/docs`.
Deployed independently from `frontend/`/`backend/` (a static build via Netlify, no server) — see
the root `README.md` for how the pieces of the repo fit together.

## Structure

```
src/
├── components/       -- Header, Footer, Hero, and each homepage section
│   └── SpotTheSlide/  -- the homepage reflex game (vanilla TS, no framework)
├── content/
│   ├── blog/          -- *.mdx posts (see schema in content.config.ts)
│   └── docs/docs/     -- Starlight API reference pages (the extra `docs/` nesting
│                          is what makes the collection route under /docs -- see below)
├── layouts/           -- BaseLayout (head/meta/analytics), MarketingLayout, BlogPostLayout
├── pages/
│   ├── index.astro    -- homepage
│   └── blog/          -- listing, post template, rss.xml
├── scripts/reveal.ts   -- shared scroll-reveal IntersectionObserver
└── styles/
    ├── tokens.css      -- design tokens (color/type/space) -- change values here, not in components
    ├── base.css        -- resets, self-hosted font-face imports, type scale
    ├── motion.css       -- [data-reveal] scroll-in animation primitive
    └── starlight-overrides.css -- remaps Starlight's theme vars onto tokens.css
```

## Design tokens

All color/type/spacing values live in `src/styles/tokens.css` as CSS custom properties (`--paper`,
`--ink`, `--accent`, `--font-display`, `--step-*` type scale, `--space-*`, etc.). Components
reference these via `var(--accent)` etc. in scoped `<style>` blocks — never hardcode a value in a
component.
Dark mode is handled via `prefers-color-scheme` plus a `data-theme` attribute override for a
manual toggle, if one is ever added.

Fonts (Fraunces for display, IBM Plex Mono for labels/code) are self-hosted via `@fontsource/*`
packages, imported in `base.css` — no external font CDN requests.

## Content

- **Blog**: add a new `.mdx` file to `src/content/blog/`. Required frontmatter: `title`,
  `description` (≤160 chars), `publishDate`. Set `draft: true` while writing — draft posts are
  excluded from the listing, individual post routes, and the RSS feed until flipped to `false`.
- **Docs**: add a new `.mdx` file to `src/content/docs/docs/` and list it in the `sidebar` array in
  `astro.config.mjs` (Starlight's sidebar is hand-ordered, not auto-generated from the file list).

## Commands

| Command           | Action                                      |
| ------------------ | -------------------------------------------- |
| `npm install`      | Install dependencies                         |
| `npm run dev`      | Start the dev server at `localhost:4321`     |
| `npm run build`    | Build the production site to `./dist/`       |
| `npm run preview`  | Preview the production build locally          |

Note: Pagefind (the `/docs` search) only builds during `npm run build` — `npm run dev` won't have
a working search box.

## Deploy

Netlify builds this directory specifically via the root `netlify.toml`'s `base = "marketing"` /
`publish = "dist"` — nothing here needs its own Netlify config. `frontend/`'s Docker deploy is
entirely separate and unaffected by anything in this directory.
