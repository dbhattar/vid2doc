# Public showcase: S3 bucket setup (local dev)

One-time setup for the bucket backing the "make this job public for a
partial refund" feature (`app/public_jobs.py`, `routes/public_jobs.py`).
Approved (and, transiently, pending/rejected -- see `app/public_jobs.py`'s
module docstring) jobs get archived here permanently, under the `public/`
prefix, and served directly from this bucket's own public URL -- never
proxied through the FastAPI app.

This doc assumes you already have:
- A bucket created (this doc uses `framewrite-local-dev-bucket` /
  `us-west-2` as the example -- substitute your own).
- The AWS CLI installed (`aws --version`).
- Credentials for an AWS account/IAM user with permission to configure this
  bucket (bucket policy, CORS, public-access-block settings) -- a personal
  admin profile, or any sufficiently-privileged user, is fine for this
  one-time setup step. This does **not** need to be the same credentials the
  app itself uses at runtime (see step 4).

Run `aws configure --profile <name>` first if you don't already have a
profile with access to this account, then pass `--profile <name>` to every
command below (omit it if you're using your default profile).

**Steps 1-3 below are automated by `deploy/configure-s3-bucket.sh`** (it
applies the same `aws s3api` calls against the policy files already saved
in `deploy/aws/`, and verifies the result with a real anonymous+CORS smoke
test) -- see that script's header comment for usage. The walkthrough below
is for understanding what it does, or for running the steps by hand.

## 1. Turn off "Block Public Access" for this bucket

New buckets block all public access by default -- the bucket policy in step
2 silently does nothing until this is turned off. Since this bucket is
dedicated to public showcase content only (nothing private shares it), it's
simplest to disable all four settings:

```bash
aws s3api put-public-access-block \
  --bucket framewrite-local-dev-bucket \
  --public-access-block-configuration \
  BlockPublicAcls=false,IgnorePublicAcls=false,BlockPublicPolicy=false,RestrictPublicBuckets=false
```

Verify:

```bash
aws s3api get-public-access-block --bucket framewrite-local-dev-bucket
```

## 2. Bucket policy: public read, scoped to `public/` only

Save as `bucket-policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PublicReadShowcasePrefix",
      "Effect": "Allow",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::framewrite-local-dev-bucket/public/*"
    }
  ]
}
```

Apply it:

```bash
aws s3api put-bucket-policy \
  --bucket framewrite-local-dev-bucket \
  --policy file://bucket-policy.json
```

Only `public/*` is world-readable -- nothing else in the bucket is exposed,
and nothing outside that prefix should ever be written there.

## 3. CORS: required for the frontend's `fetch()`, not just `<img>`/`<a>`

The frontend reads the archived markdown's text via `fetch()` (see
`DocumentPreview.tsx`'s `external` mode) -- that needs real CORS headers,
unlike an `<img src>` or a plain download link, which work cross-origin
without any CORS configuration at all. Without this step, the file loads
fine if you paste its URL directly into a browser tab, but the app's
`fetch()` call fails silently.

Save as `cors-config.json`:

```json
{
  "CORSRules": [
    {
      "AllowedOrigins": ["*"],
      "AllowedMethods": ["GET"],
      "AllowedHeaders": ["*"],
      "MaxAgeSeconds": 3000
    }
  ]
}
```

`AllowedOrigins: ["*"]` is appropriate here (not a security shortcut) -- this
content is meant to be fully public, so there's no origin that should be
treated differently from any other.

Apply it:

```bash
aws s3api put-bucket-cors \
  --bucket framewrite-local-dev-bucket \
  --cors-configuration file://cors-config.json
```

## 4. Credentials for the app itself (`backend/.env`)

The running app (not your AWS CLI session above) needs its own credentials
to upload/delete archived files -- `boto3`'s own default credential chain
picks these up from plain environment variables (see `app/s3_client.py`),
not proxied through `Settings` the way most other config here is.

**For local dev, reusing the same credentials you used in steps 1-3 is
fine.** For anything beyond local testing, scope a dedicated IAM user to
just this bucket's `public/` prefix instead -- it only ever needs object-level
access, never bucket-policy/CORS/public-access-block permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "FramewriteShowcaseObjectAccess",
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::framewrite-local-dev-bucket/public/*"
    },
    {
      "Sid": "FramewriteShowcaseListForCleanup",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::framewrite-local-dev-bucket",
      "Condition": { "StringLike": { "s3:prefix": "public/*" } }
    }
  ]
}
```
(`ListBucket` is for `app/public_jobs.py`'s `delete_s3_archive`, which pages
through a rejected submission's objects to remove them.)

Either way, fill in `backend/.env` directly (never commit real values):

```
AWS_ACCESS_KEY_ID=<the access key id>
AWS_SECRET_ACCESS_KEY=<the secret access key>
```

`PUBLIC_ARCHIVE_S3_BUCKET`, `PUBLIC_ARCHIVE_S3_REGION`, and
`PUBLIC_ARCHIVE_BASE_URL` should already be filled in (see `.env.example`
for what each one means) -- for a bucket with no CDN in front, the base URL
is the bucket's own virtual-hosted-style endpoint:
`https://<bucket>.s3.<region>.amazonaws.com`.

Restart the containers so the app picks up the new env vars:

```bash
./restart-containers.sh --dev
```

## 5. Verify

```bash
# Policy and CORS actually took effect
aws s3api get-bucket-policy --bucket framewrite-local-dev-bucket
aws s3api get-bucket-cors --bucket framewrite-local-dev-bucket

# A real object under public/ is readable with no credentials at all, and
# carries the right CORS header
echo "test" > /tmp/showcase-test.txt
aws s3 cp /tmp/showcase-test.txt s3://framewrite-local-dev-bucket/public/showcase-test.txt
curl -i https://framewrite-local-dev-bucket.s3.us-west-2.amazonaws.com/public/showcase-test.txt
curl -i -H "Origin: http://localhost:3000" \
  https://framewrite-local-dev-bucket.s3.us-west-2.amazonaws.com/public/showcase-test.txt \
  | grep -i access-control
aws s3 rm s3://framewrite-local-dev-bucket/public/showcase-test.txt
```

Then exercise the real feature end-to-end: opt a completed `job_type=="video"`
job into the public showcase from its job detail page, approve it from
`/admin/public-jobs`, and confirm `GET /api/public/showcase` lists it with a
working `document_url`.
