# Framewrite frontend

Next.js (App Router) product frontend: login, submit conversions, track
jobs, download documents, manage API keys, and manage wallet billing
(pay-as-you-go, $1/video-hour — no subscriptions). Separate from the static
marketing site at the repo root — this is the actual signed-in application,
talking to `../backend`'s API.

## Auth

"Sign in with Google" (Google Identity Services, via `@react-oauth/google`)
gets an ID token client-side, which is exchanged for an app session token at
`POST /api/auth/google`. The token is stored in `localStorage`
(`lib/auth.ts`) and attached as `Authorization: Bearer <token>` on every
backend call by the one fetch wrapper in `lib/api.ts` — no other file should
call `fetch` against the backend directly.

There's no server-side session: every page that needs auth is a Client
Component that checks `getToken()` on mount and redirects to `/login` if
missing (see `app/dashboard/page.tsx` for the pattern).

## Local development

```bash
cd frontend
cp .env.example .env.local   # fill in NEXT_PUBLIC_GOOGLE_CLIENT_ID
npm install
npm run dev
```

Requires the backend running separately (see `../backend/README.md`) at
whatever `NEXT_PUBLIC_API_BASE_URL` points to (defaults to
`http://localhost:8000`).

`.env.local` variables:

| Variable | Purpose |
|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | Public URL the browser uses to reach the backend API |
| `NEXT_PUBLIC_GOOGLE_CLIENT_ID` | Same Google OAuth Web Client ID as the backend's `GOOGLE_CLIENT_ID` |

Both are `NEXT_PUBLIC_` vars, meaning they're inlined into the JS bundle at
**build time** — changing them requires a rebuild, not just a container
restart.

## Deployment

Dockerized alongside the backend, not deployed to Vercel/Netlify — see the
`frontend` service in `../backend/docker-compose.yml`. The `Dockerfile` uses
Next.js's standard multi-stage `output: "standalone"` build. Because the
`NEXT_PUBLIC_*` vars are build-time, they're passed as Docker build args
(sourced from `../backend/.env` when building via that compose file), not
runtime environment variables.
