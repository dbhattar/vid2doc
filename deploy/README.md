# Deployment (Fabric)

Deploys the whole stack (Postgres, API, worker, frontend, all via
`backend/docker-compose.yml`) to a single Ubuntu/Debian VPS, with nginx as
the reverse proxy and Let's Encrypt for TLS. Two domains:
`app.framewrite.cc` (frontend) and `api.framewrite.cc` (backend API).

See `fabfile.py`'s module docstring for the exact command sequence
(create-deploy-user → bootstrap → fill `.env` by hand → point DNS →
`setup-tls` → `deploy`). This file covers the *why*; that one covers the
*how to run it*.

## Setup

```bash
cd deploy
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

## Before you run anything

Edit the constants at the top of `fabfile.py`:

- `APP_DIR` — where the repo lives on the VPS (default `/opt/framewrite`)
- `GIT_REPO_URL` — defaults to this repo's own SSH remote, which means the
  VPS needs its own deploy key (steps are in a comment right above
  `NGINX_CONF` in `fabfile.py`). Switch to the HTTPS clone URL instead if
  the repo is public and you'd rather skip that.
- `CERTBOT_EMAIL` — real email for Let's Encrypt expiry/renewal notices

## Convenience wrapper: `run.sh`

`fab -H user@IP -i ~/.ssh/key <task>` gets repetitive across a deploy
session. `run.sh` reads the connection details from environment variables
instead:

```bash
export VPS_IP=1.2.3.4        # set once per shell session

SSH_USER=root ./run.sh create-deploy-user     # root, one-time only
./run.sh bootstrap                            # everything else defaults to deploy
./run.sh setup-tls
./run.sh deploy
./run.sh logs --service=worker --lines=200
./run.sh set-env --key=TRANSCRIPTION_ENGINE --value=baseten
```

`SSH_USER` defaults to `deploy`; `SSH_KEY` defaults to
`~/.ssh/framewrite_vps` — override either as an env var if yours differ.

## Why `.env`'s secret values are never hardcoded

No task here hardcodes any of `backend/.env`'s actual secret values (Stripe
live key, JWT secret, Postgres password) — nothing here should ever bake a
real secret into a script that might get committed, logged, or shared.
`bootstrap` prints a reminder to create the file by hand; `deploy` refuses to
run at all if it's missing, specifically to prevent ever accidentally
starting production with the insecure dev defaults from `.env.example`.

`set-env` is the one task that *does* write into `.env`, but it never breaks
the rule above: the value it writes only ever comes from whatever you type
on the command line for that one invocation (e.g.
`--value=$STRIPE_SECRET_KEY` from your own shell), never from anything
hardcoded in `fabfile.py`. It edits the file locally (downloaded, changed,
re-uploaded) rather than via a remote shell command with the value
interpolated in, so the value never touches the VPS's own shell history or
risks breaking on special characters.

## Why `git reset --hard` is safe here

`deploy` runs `git fetch` + `git reset --hard origin/main` on the VPS to
pick up the latest commit. This only touches *tracked* files. `backend/.env`
and `backend/data/` (Postgres's data dir, uploads, generated documents) are
both gitignored — untracked — so a hard reset can never touch either of
them, no matter what.

## Tasks

| Task | What it does |
|---|---|
| `create-deploy-user` | One-time, connected as **root**: creates `DEPLOY_USER` (default `deploy`), grants it passwordless sudo, copies root's `authorized_keys` so it can log in with the same key. Every other task below connects as `DEPLOY_USER`, not root. Idempotent. |
| `bootstrap` | One-time: installs Docker/nginx/certbot, clones the repo, writes the (HTTP-only) nginx config. Idempotent — re-running it skips anything already done. |
| `setup-tls` | Provisions Let's Encrypt certs for both domains via certbot's nginx plugin (also patches nginx to add HTTPS + redirect). Run once DNS for both domains resolves to the server. |
| `deploy` | Pulls the latest commit, rebuilds changed images, restarts the stack. This is what you run for every subsequent deploy. |
| `restart` | Recreates containers without rebuilding images — e.g. after hand-editing `.env`. Runs `docker compose up -d`, not `docker compose restart`: the latter never re-reads `.env`/`env_file` at all, since that's only evaluated on container creation. |
| `logs` | Tails one service's logs: `fab ... logs --service=worker --lines=200`. |
| `set-env` | Updates (or adds) one `KEY=VALUE` line in `backend/.env` from the command line: `fab ... set-env --key=TRANSCRIPTION_ENGINE --value=baseten`. Restarts the stack afterward by default so it takes effect — pass `--no-restart-after` to batch several `set-env` calls before one restart. |

## S3 buckets

The app uses two kinds of S3 bucket, each with its own IAM user. Each bucket has
its own script in this directory, which creates the bucket if it doesn't exist
and applies the policy documents in `aws/`. Both need the AWS CLI v2 and a profile (`aws configure
--profile framewrite-admin`) that can manage S3 and IAM. That is an *admin*
identity, not the app's own runtime user.

**Which profile to use.** List the profiles on your machine, then check which
identity one resolves to:

```bash
aws configure list-profiles                          # names only
aws sts get-caller-identity --profile <profile>      # the account and ARN it runs as
aws configure list --profile <profile>               # its settings, secrets masked
```

The `Arn` from `get-caller-identity` shows whose credentials the profile uses.
`--profile` for these scripts must be an admin identity, never the app's own
IAM user (the one whose key is in `backend/.env`). If you don't have an admin
profile yet, create one with `aws configure --profile framewrite-admin`.
Profile names live in `~/.aws/config` and `~/.aws/credentials`.

| Bucket | Script | Holds | Access |
|---|---|---|---|
| Public showcase (`PUBLIC_ARCHIVE_S3_BUCKET`) | `configure-s3-bucket.sh` | Documents and videos a user chose to publish | Public read under `public/*`, plus CORS |
| Private job storage (`JOB_STORAGE_S3_BUCKET`) | `configure-job-bucket.sh` (plus `configure-job-iam-user.sh` for its IAM user) | Every finished job's documents and original upload | Nobody directly; only the job IAM user |

### Private job storage

With a job bucket set, a loop in the worker uploads each finished job to S3
and frees the VPS disk. Files then stay until the user deletes the job,
instead of being swept after 7 days. Users never touch the bucket: the API
checks that they own the job, then streams the file or hands out a 5-minute
presigned URL for that one file. While `JOB_STORAGE_S3_BUCKET` is empty,
nothing changes (files stay on local disk and are swept by `retention.py`).

There are two buckets, one per environment, and **one IAM user** for the app's
access to them:

| | Local development | Production |
|---|---|---|
| Bucket | `framewrite-jobs-dev` | `framewrite-jobs-prod` |
| `--app-origin` | `http://localhost:3000` | `https://app.framewrite.cc` |

The job IAM user is separate from the showcase bucket's (`AWS_ACCESS_KEY_ID`
in `backend/.env`), so neither identity can reach the other's bucket. Its
credentials go in their own variables, `JOB_STORAGE_AWS_ACCESS_KEY_ID` and
`JOB_STORAGE_AWS_SECRET_ACCESS_KEY`. Do the steps in this order.

**1. Create the IAM user and its policy: `configure-job-iam-user.sh`.**

```bash
./configure-job-iam-user.sh --profile framewrite-admin --iam-user framewrite-jobs --create-user
```

This creates the user if it doesn't exist (skip `--create-user` if you made it
already), attaches the inline policy `FramewriteJobStorageAccess`
(`aws/job-bucket-user-access.json`) and checks it with the IAM policy
simulator. The policy allows put, get, delete and abort-multipart-upload on
`jobs/*` plus listing that prefix, in **both** buckets, and nothing else. It
needs no bucket to exist yet.

| Flag | Meaning |
|---|---|
| `--profile` | An admin AWS profile (see "Which profile to use"). Needs `iam:GetUser` and `iam:PutUserPolicy`; also `iam:CreateUser`, `iam:CreateAccessKey`/`ListAccessKeys` and `iam:SimulatePrincipalPolicy` for the optional parts. |
| `--iam-user` | The job IAM user's name. |
| `--buckets` | Optional, comma-separated. Defaults to `framewrite-jobs-dev,framewrite-jobs-prod`. The policy is replaced on every run, so list every bucket the user should reach. |
| `--create-user` | Create the user if it doesn't exist. |
| `--create-access-key` | Create an access key and print `JOB_STORAGE_AWS_ACCESS_KEY_ID=...` and `JOB_STORAGE_AWS_SECRET_ACCESS_KEY=...` **once**. Copy them straight into `backend/.env` (local) or run `./run.sh set-env` for each (production). A user can hold two keys at most. |

**2. Create each bucket: `configure-job-bucket.sh`.** Run it once per bucket
(this also creates the bucket if it's missing):

```bash
# local development
./configure-job-bucket.sh --profile framewrite-admin --bucket framewrite-jobs-dev \
    --region us-east-1 --iam-user framewrite-jobs --app-origin http://localhost:3000

# production
./configure-job-bucket.sh --profile framewrite-admin --bucket framewrite-jobs-prod \
    --region us-east-1 --iam-user framewrite-jobs --app-origin https://app.framewrite.cc
```

| Flag | Meaning |
|---|---|
| `--profile` | The admin profile. Needs `s3:CreateBucket` and the bucket-management permissions, `iam:GetUser` and `sts:GetCallerIdentity`. |
| `--bucket` | Bucket name, globally unique across AWS. Must **not** be the showcase bucket. |
| `--region` | Where to create it. If it differs from `PUBLIC_ARCHIVE_S3_REGION` (default `us-east-1`), also set `JOB_STORAGE_S3_REGION` in `backend/.env`. |
| `--iam-user` | The job IAM user from step 1. It is allowed in the bucket policy, so it must exist. |
| `--app-origin` | The frontend's exact origin: scheme, host and port, no trailing slash (`http://localhost:3000`, not `http://localhost`). CORS allows `GET` from it only, which presigned video/audio playback needs. One origin per bucket. |

For each bucket the script turns on all four Block Public Access settings,
disables ACLs, enables default encryption (SSE-S3), and applies a bucket
policy that denies any non-TLS request and denies every principal except the
job IAM user and the identity you ran the script with (so you can't lock
yourself out). It adds CORS for `GET` from `--app-origin`, then uploads a
throwaway object and checks that an anonymous request gets `403`; it exits
with an error if the bucket is somehow readable. It is safe to re-run. It
does **not** touch the IAM user's permissions: that is step 1.

**3. Configure the app.** In `backend/.env`:

```bash
JOB_STORAGE_S3_BUCKET=framewrite-jobs-dev        # production: framewrite-jobs-prod
JOB_STORAGE_AWS_ACCESS_KEY_ID=...                # from step 1
JOB_STORAGE_AWS_SECRET_ACCESS_KEY=...
JOB_STORAGE_S3_REGION=                           # only if not the same as PUBLIC_ARCHIVE_S3_REGION
```

Locally, rebuild with `./restart-containers.sh --dev`. In production, set each
one and restart (each `set-env` restarts the stack unless you pass
`--no-restart-after`):

```bash
./run.sh set-env --key=JOB_STORAGE_S3_BUCKET --value=framewrite-jobs-prod --no-restart-after
./run.sh set-env --key=JOB_STORAGE_AWS_ACCESS_KEY_ID --value=... --no-restart-after
./run.sh set-env --key=JOB_STORAGE_AWS_SECRET_ACCESS_KEY --value=...
```

If the two key variables are empty the app falls back to boto3's default
credential chain, which here is the showcase user, and the bucket policy
refuses it. Optionally set `JOB_STORAGE_SYNC_FROM=<ISO date>` to leave jobs
created before that date on local disk with the 7-day sweep instead of
uploading everything still on disk. Check the worker logs
(`./run.sh logs --service=worker`) for jobs being stored. A failed upload keeps
the job on local disk and is retried about every 15 minutes.

**Good to know**

- Each bucket's policy allows only the identity that ran the script last. If a
  teammate re-runs it with their own profile, they replace you as the admin
  principal. Everyone else, including other IAM users in your account, is
  denied by design. If you ever lock yourself out, the AWS account's root user
  can still delete the bucket policy.
- When someone makes a job public or enables chat, its files are streamed
  through the app from the job bucket (read as the job user) into the showcase
  bucket (written as the showcase user). A server-side S3 copy would need one
  identity with access to both buckets, which would defeat the separation, so
  the job user gets no access to the showcase bucket and the showcase user
  none to the job bucket.
- For `framewrite-jobs-dev` it's easiest to keep one IAM user for both
  environments, as above. If you'd rather isolate production, create a second
  user (e.g. `framewrite-jobs-prod`) with `--buckets framewrite-jobs-prod` and
  pass that user as `--iam-user` when configuring the prod bucket.
- Incomplete multipart uploads aren't cleaned up automatically. The policy
  lets the app abort a failed upload itself, but a bucket lifecycle rule that
  aborts incomplete uploads after a few days is a worthwhile safety net.
- The design is in `plan/private-job-storage-plan.md`.

## Notes

- Every privileged step uses `c.sudo(...)`. Passwordless sudo for the SSH
  user is simplest; otherwise pass `--prompt-for-sudo-password` to `fab`.
- Migrations run automatically — `docker-entrypoint.sh` (inside the image)
  runs `alembic upgrade head` before the `api`/`worker` processes start, so
  `deploy` never needs a separate migration step.
- The nginx config sets `client_max_body_size 2100M` and disables request
  buffering on the API domain specifically — without it, nginx would reject
  large video uploads with a 413 before FastAPI ever saw them.
