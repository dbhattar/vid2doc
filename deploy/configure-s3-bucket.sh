#!/usr/bin/env bash
# Configures an S3 bucket for the public-showcase feature (see
# backend/app/public_jobs.py, backend/s3-showcase-setup.md): disables Block
# Public Access, applies the public-read bucket policy and CORS config, and
# (optionally) attaches the app's own least-privilege object-access policy
# to an existing IAM user. The three policy documents live in deploy/aws/ --
# this script just applies them via the AWS CLI, under whichever --profile
# you pass, rather than copy-pasting the same handful of `aws` commands by
# hand every time (see backend/s3-showcase-setup.md for what each one does
# and why, if you want the manual walkthrough instead).
#
# Usage (run from *this* `deploy/` directory, or from anywhere -- it cd's to
# its own location first so deploy/aws/*.json resolves either way):
#
#   aws configure --profile framewrite-s3   # one-time, if you don't already
#                                            # have a profile with access to
#                                            # this bucket/account
#
#   ./configure-s3-bucket.sh --profile framewrite-s3 --bucket framewrite-local-dev-bucket --region us-west-2
#
#   # Also attach deploy/aws/user-access.json to the IAM user the app itself
#   # authenticates as (backend/.env's AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY) --
#   # optional, skip this flag if you'd rather attach it by hand:
#   ./configure-s3-bucket.sh --profile framewrite-s3 --bucket framewrite-local-dev-bucket --region us-west-2 --iam-user framewrite-showcase
#
# --profile needs permission to manage the bucket itself (policy/CORS/public-
# access-block) and, if --iam-user is given, IAM:PutUserPolicy -- this does
# NOT need to be (and for least privilege, should not be) the same identity
# as --iam-user, which only ever needs object-level S3 access at runtime.

set -euo pipefail

cd "$(dirname "$0")"

PROFILE=""
BUCKET=""
REGION=""
IAM_USER=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)
      PROFILE="$2"
      shift 2
      ;;
    --bucket)
      BUCKET="$2"
      shift 2
      ;;
    --region)
      REGION="$2"
      shift 2
      ;;
    --iam-user)
      IAM_USER="$2"
      shift 2
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$PROFILE" || -z "$BUCKET" || -z "$REGION" ]]; then
  echo "Usage: $0 --profile <aws-profile> --bucket <bucket-name> --region <region> [--iam-user <iam-username>]" >&2
  exit 1
fi

AWS_ARGS=(--profile "$PROFILE" --region "$REGION")

# aws/bucket-policy.json and aws/user-access.json have the example bucket
# name (framewrite-local-dev-bucket) baked into their Resource ARNs -- a
# bucket policy's ARNs must reference the bucket it's applied to, or AWS
# rejects it outright (MalformedPolicy: Policy has invalid resource), so
# rewrite the ARNs to the real --bucket before applying rather than relying
# on the checked-in files happening to already match.
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

render_policy() {
  sed "s/framewrite-local-dev-bucket/${BUCKET}/g" "$1"
}

echo "==> Disabling Block Public Access on $BUCKET"
aws "${AWS_ARGS[@]}" s3api put-public-access-block \
  --bucket "$BUCKET" \
  --public-access-block-configuration BlockPublicAcls=false,IgnorePublicAcls=false,BlockPublicPolicy=false,RestrictPublicBuckets=false

echo "==> Applying bucket policy (public read, scoped to public/*) -- aws/bucket-policy.json"
render_policy aws/bucket-policy.json > "$TMP_DIR/bucket-policy.json"
aws "${AWS_ARGS[@]}" s3api put-bucket-policy --bucket "$BUCKET" --policy "file://$TMP_DIR/bucket-policy.json"

echo "==> Applying CORS configuration -- aws/cors-config.json"
aws "${AWS_ARGS[@]}" s3api put-bucket-cors --bucket "$BUCKET" --cors-configuration file://aws/cors-config.json

if [[ -n "$IAM_USER" ]]; then
  echo "==> Attaching object-level access policy to IAM user '$IAM_USER' -- aws/user-access.json"
  render_policy aws/user-access.json > "$TMP_DIR/user-access.json"
  aws "${AWS_ARGS[@]}" iam put-user-policy \
    --user-name "$IAM_USER" \
    --policy-name FramewriteShowcaseObjectAccess \
    --policy-document "file://$TMP_DIR/user-access.json"
else
  echo "==> Skipping IAM user policy attachment (no --iam-user given) -- see aws/user-access.json"
fi

echo "==> Verifying bucket-level config"
aws "${AWS_ARGS[@]}" s3api get-public-access-block --bucket "$BUCKET"
aws "${AWS_ARGS[@]}" s3api get-bucket-policy --bucket "$BUCKET"
aws "${AWS_ARGS[@]}" s3api get-bucket-cors --bucket "$BUCKET"

BASE_URL="https://${BUCKET}.s3.${REGION}.amazonaws.com"

echo "==> Smoke test: uploading a throwaway object and confirming anonymous + CORS access"
TMP_FILE="$(mktemp)"
echo "framewrite public showcase bucket check" > "$TMP_FILE"
TEST_KEY="public/_bucket-config-check.txt"
aws "${AWS_ARGS[@]}" s3 cp "$TMP_FILE" "s3://${BUCKET}/${TEST_KEY}" >/dev/null
rm -f "$TMP_FILE"

HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/${TEST_KEY}")
CORS_HEADER=$(curl -s -D - -o /dev/null -H "Origin: http://localhost:3000" "${BASE_URL}/${TEST_KEY}" | grep -i "access-control-allow-origin" || true)

aws "${AWS_ARGS[@]}" s3 rm "s3://${BUCKET}/${TEST_KEY}" >/dev/null

if [[ "$HTTP_STATUS" != "200" ]]; then
  echo "ERROR: anonymous GET of ${BASE_URL}/${TEST_KEY} returned HTTP $HTTP_STATUS, expected 200 -- check the bucket policy and Block Public Access settings above." >&2
  exit 1
fi
if [[ -z "$CORS_HEADER" ]]; then
  echo "ERROR: no Access-Control-Allow-Origin header on the response -- check the CORS configuration above." >&2
  exit 1
fi

echo "==> Done. $BUCKET is publicly readable under public/ with CORS enabled."
echo "    Base URL for backend/.env's PUBLIC_ARCHIVE_BASE_URL: $BASE_URL"
