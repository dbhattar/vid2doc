# Replace anonymous trial upload with a signup bonus credit

## Context

Today, unauthenticated visitors can upload a video (≤10 min) or audio
(≤30 min) file for free via `routes/trial.py`, capped at 2/day per IP and
gated by Cloudflare Turnstile, with jobs hard-deleted after 6 hours. This
whole subsystem exists specifically as a stand-in for auth+billing on
anonymous traffic (per that file's own docstring).

The user wants to remove unauthenticated processing entirely and instead
grant every new signup a one-time wallet credit worth 10 minutes of video
processing — simpler (no parallel anonymous-job code path, no per-IP
abuse-prevention machinery), and a stronger incentive to actually create an
account rather than just clicking a demo button.

**Decided with the user**: no replacement homepage section for the removed
trial upload block — just remove it, and mention the signup credit in the
pricing section instead. No demo/preview content added for anonymous
visitors either — this is a clean removal, not a replacement feature.

**Key existing-system fact that makes this easy**: the wallet is one
fungible balance per user (`WalletLedgerEntry`, summed, not earmarked by job
type). So a single "10 minutes of video" credit isn't video-only in
practice — a new user can spend it on audio or video_gen too, just
proportional to that job type's rate (e.g. the same credit covers a longer
audio clip than video, since audio is cheaper per hour). Nothing extra
needs building for that — it falls out of the existing rate/balance system.

## Design

1. **New ledger entry type**: `WalletLedgerEntry.entry_type` already just a
   plain string column (`topup` / `usage_charge` / `usage_refund` today,
   `app/models.py`) — add `"signup_bonus"` as a fourth value. No schema
   change needed. `billing.net_spent_cents`/`total_revenue_cents` both
   already filter by an explicit type list, so a new type is automatically
   invisible to both (correct — a bonus is neither revenue nor spend), while
   `get_wallet_balance_cents` (a plain `SUM`) picks it up automatically.
2. **New `billing.grant_signup_bonus(user_id)`**, mirroring
   `credit_topup`'s shape: computes the credit via the *existing* rate
   function, `cost_for_duration_cents(SIGNUP_BONUS_VIDEO_MINUTES * 60,
   "video")` — dynamic, not a hardcoded cent value, so it stays "10 minutes
   of video, at whatever the current rate is" even if pricing changes later
   — then inserts a `signup_bonus` ledger entry for that amount.
3. **New config**: `SIGNUP_BONUS_VIDEO_MINUTES = 10` in `config.py`.
4. **Signup hook**: `routes/auth.py` already has exactly the right signal —
   `get_or_create_user_by_google`'s `is_new` return value, which already
   gates the welcome-email trigger. Add
   `if is_new: billing.grant_signup_bonus(user["id"])` there. Deliberately
   **not** tied to `ALWAYS_SEND_WELCOME_EMAIL` (that debug flag re-sends the
   welcome email on every login for local iteration — reusing it for the
   bonus would re-grant credit on every login in that mode).

## Remove the anonymous trial subsystem

**Backend:**
- Delete `app/routes/trial.py` entirely; remove its router registration in
  `app/main.py`.
- Remove the four trial-only functions in `app/jobs.py`:
  `count_trial_jobs_from_ip_since`, `list_trial_jobs_eligible_for_cleanup`,
  `count_trial_jobs`, `list_trial_jobs`.
- `retention.py`: remove `_cleanup_trial_jobs()` and its call in `main()`.
- `app/routes/admin.py`: remove the `trial_job_count` stat from
  `GET /api/admin/stats` and the whole `GET /api/admin/trial-jobs` endpoint.
- `app/pipeline.py::run_job`: remove the `if job.get("user_id") is None:`
  branch (auto-caption-everything for anonymous jobs) — dead code once
  `trial.py` is gone, since nothing else ever creates a `user_id=None` job.
- `config.py`: remove `TRIAL_MAX_VIDEO_DURATION_SECONDS`,
  `TRIAL_MAX_AUDIO_DURATION_SECONDS`, `TRIAL_MAX_UPLOAD_BYTES`,
  `TRIAL_MAX_PER_IP_PER_DAY`, `TRIAL_RETENTION_HOURS`. **Keep**
  `TURNSTILE_SECRET_KEY` — confirmed `routes/feedback.py`'s anonymous
  feedback-widget endpoint independently uses the same
  `turnstile.verify_turnstile_token`, unrelated to the trial.
- Leave the `Job.client_ip` column as-is (nullable, just stops being
  populated) — confirmed via grep it's only ever written by `trial.py` and
  only ever queried by the trial-only function being removed; dropping the
  column would be a migration for no real benefit.
- Remove `backend/tests/test_trial_flow.py` (tests a route that no longer
  exists).

**Frontend (app) admin dashboard**
(`frontend/app/(app)/admin/page.tsx`): remove the `AdminTrialJob` type, the
"Anonymous trials" stat card, the trial-jobs table section, and
`trial_job_count` from the `AdminStats` type.

**Marketing site:**
- Delete `marketing/src/components/TrialUpload/` entirely; remove its
  import/usage from `index.astro` — no replacement section, per the user's
  decision.
- `PricingTable.astro`: add a mention of the signup bonus (exact copy/
  placement — e.g. a line under the section intro — worked out at
  implementation time to match the section's existing tone).
- `FAQ.astro`: rewrite the four trial-referencing entries — "What does the
  free trial actually let me do?" becomes something like "Do I need to add
  money right away?" (answering with the signup-bonus policy); "What
  happens to my file afterward?" drops the trial-vs-account contrast, just
  states the signed-up retention policy; "How accurate is it?" swaps
  "run a clip through the free trial" for "run a short clip using your
  signup credit"; "What do I get with an account that I don't get with the
  trial?" no longer makes sense once there's no separate trial — remove it.
- `privacy.astro`: remove/reword the trial-specific IP-address, GA-event,
  and localStorage copy; reword the Turnstile section to describe the
  feedback form (still real, still uses it) instead of "the free trial's
  upload form."
- `.env.example` (marketing): update the `PUBLIC_TURNSTILE_SITE_KEY`
  comment, which currently says "the trial widget's bot-check," to mention
  the feedback widget instead.

## Risks

- **Abuse vector shifts, doesn't disappear**: someone could create multiple
  Google accounts to farm signup credits, same as the trial's per-IP cap
  was defending against multiple anonymous uploads. This is meaningfully
  higher-friction than the old anonymous flow (a real Google account per
  attempt vs. just clicking a button), which is exactly the tradeoff the
  user is asking for — not treating this as something needing new
  anti-abuse tooling right now.
- **Don't remove shared Turnstile infra**: `TURNSTILE_SECRET_KEY`,
  `PUBLIC_TURNSTILE_SITE_KEY`, `turnstile.py`, and the global Cloudflare
  script tag in `marketing/src/layouts/BaseLayout.astro` are all shared
  with the unrelated feedback widget — easy to mistakenly delete these
  thinking trial was their only user.

## Verification

- Unit-test `billing.grant_signup_bonus`: balance increases by the right
  (dynamically-computed) amount, recorded as `entry_type="signup_bonus"`,
  and confirm it does NOT appear in `net_spent_cents` or
  `total_revenue_cents`.
- Test `/api/auth/google`: bonus granted exactly once on first login, not
  re-granted on subsequent logins, and not re-granted every login even when
  `ALWAYS_SEND_WELCOME_EMAIL=true` (dev-only flag).
- Confirm `routes/trial.py`'s old endpoints now 404, and the app still
  boots cleanly (no leftover import of the removed router in `main.py`).
- Confirm existing charge/refund flows (`charge_for_job`,
  `refund_job_charge`, real video/audio/video_gen uploads) are completely
  unaffected — this change only adds a new billing function and removes the
  trial subsystem, it doesn't modify any shared charging code path.
- `npm run build` on the marketing site after the copy changes; manually
  read through the updated FAQ and new pricing-section copy for coherence.
- End-to-end: sign up with a fresh Google account, confirm the wallet
  balance immediately reflects the bonus, and confirm it can actually be
  spent on a real conversion.
