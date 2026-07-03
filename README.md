# vid2doc

Turn any video into a searchable document — automatic transcription, speaker
diarization, relevant frame capture, and clean document formatting.

This repo currently contains the **landing page and waitlist** for vid2doc,
used to validate interest before the full product is built.

## Live site

Deployed on Netlify from the `main` branch. (Add the live URL here once the
site is deployed.)

## Tech stack

Plain static HTML/CSS/JS — no framework, no build step.

- `index.html` — landing page (hero, waitlist form, feature overview)
- `thanks.html` — no-JS fallback confirmation page
- `styles.css` — all styling
- `script.js` — progressive-enhancement AJAX submit for the waitlist form
- `netlify.toml` — Netlify publish config
- `assets/` — static assets (favicon)

## Waitlist form

Signups (name + email) are captured with [Netlify
Forms](https://docs.netlify.com/manage/forms/setup/) — no backend or
third-party service required:

- The form in `index.html` is marked with `data-netlify="true"`, so Netlify
  detects and registers it at deploy time.
- With JavaScript enabled, `script.js` submits the form via `fetch()` and
  swaps in an inline success message.
- Without JavaScript, the form falls back to a normal POST to `thanks.html`.
- A hidden honeypot field (`bot-field`) filters spam submissions.
- Submissions appear under **Site → Forms → waitlist** in the Netlify
  dashboard. Enable **Form notifications** there to get an email/Slack alert
  per signup.

Note: form submission only works on an actual Netlify deploy (or via
`netlify dev`) — opening `index.html` directly or serving it with a plain
static server will not record submissions, since Netlify registers the form
at build time.

## Local development

No build step — just serve the directory and open it in a browser:

```bash
python3 -m http.server 8080
# then open http://localhost:8080
```

To test the actual form submission locally, use the [Netlify
CLI](https://docs.netlify.com/cli/get-started/) instead:

```bash
npm install -g netlify-cli
netlify dev
```

## Deployment

The site deploys to Netlify directly from this GitHub repo:

1. In Netlify: **Add new site → Import an existing project → GitHub** → select this repo.
2. Build settings: no build command, publish directory `.` (already set in `netlify.toml`).
3. Every push to `main` triggers a redeploy.

## Roadmap

The full product, once built, will:

- [ ] Extract audio from video, transcribe, and diarize speakers
- [ ] Extract image frames from video at intervals
- [ ] Detect which frames carry meaningful information and match them to the
      surrounding transcript
- [ ] Format the transcript into a document with proper headings and titles
- [ ] Insert relevant frame images into the document at the right places

The end goal: make video content searchable by topic without having to
rewatch it.
