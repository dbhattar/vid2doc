#!/usr/bin/env bash
# Creates (if needed) and configures a PRIVATE S3 bucket that holds every
# finished job's documents and original uploads (see backend/app/job_storage.py,
# JOB_STORAGE_S3_BUCKET). Unlike configure-s3-bucket.sh (public showcase),
# nothing here is public:
#   - all four Block Public Access settings on
#   - ACLs disabled (bucket-owner-enforced)
#   - default encryption (SSE-S3)
#   - a bucket policy that denies non-TLS requests and denies every principal
#     except the job-storage IAM user and your admin identity
#   - CORS for GET from the app origin only (presigned media playback)
# Users never touch the bucket: the API checks ownership, then streams a file
# or issues a 5-minute presigned URL for one key.
#
# Run it once per bucket -- framewrite-jobs-dev for local development and
# framewrite-jobs-prod for production. The IAM user's own permissions are NOT
# set here: run configure-job-iam-user.sh first (it creates the user if needed
# and grants it access to both buckets), because this script needs the user to
# exist to allow it in the bucket policy.
#
# Usage:
#   ./configure-job-bucket.sh --profile framewrite-admin --bucket framewrite-jobs-dev \
#       --region us-east-1 --iam-user framewrite-jobs --app-origin http://localhost:3000
#
#   ./configure-job-bucket.sh --profile framewrite-admin --bucket framewrite-jobs-prod \
#       --region us-east-1 --iam-user framewrite-jobs --app-origin https://app.framewrite.cc
#
# --app-origin is the frontend's exact origin (scheme, host and port, no
# trailing slash); one origin per bucket.
# --profile must be able to manage the bucket; its own ARN is kept allowed in
# the bucket policy so you can't lock yourself out.

set -euo pipefail
cd "$(dirname "$0")"

PROFILE="" BUCKET="" REGION="" IAM_USER="" APP_ORIGIN=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile) PROFILE="$2"; shift 2 ;;
    --bucket) BUCKET="$2"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    --iam-user) IAM_USER="$2"; shift 2 ;;
    --app-origin) APP_ORIGIN="$2"; shift 2 ;;
    *) echo "ERROR: unknown argument: $1" >&2; exit 1 ;;
  esac
done
if [[ -z "$PROFILE" || -z "$BUCKET" || -z "$REGION" || -z "$IAM_USER" || -z "$APP_ORIGIN" ]]; then
  echo "Usage: $0 --profile <p> --bucket <b> --region <r> --iam-user <app-iam-user> --app-origin <https://...>" >&2
  exit 1
fi

AWS_ARGS=(--profile "$PROFILE" --region "$REGION")
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

APP_ARN="$(aws "${AWS_ARGS[@]}" iam get-user --user-name "$IAM_USER" --query User.Arn --output text)"
ADMIN_ARN="$(aws "${AWS_ARGS[@]}" sts get-caller-identity --query Arn --output text)"
# An assumed-role caller shows up as arn:...:assumed-role/Role/session; the
# policy condition needs the role ARN instead.
if [[ "$ADMIN_ARN" == *":assumed-role/"* ]]; then
  ACCOUNT="$(echo "$ADMIN_ARN" | cut -d: -f5)"
  ROLE="$(echo "$ADMIN_ARN" | cut -d/ -f2)"
  ADMIN_ARN="arn:aws:iam::${ACCOUNT}:role/${ROLE}"
fi

render() {
  sed -e "s#framewrite-jobs-prod#${BUCKET}#g" \
      -e "s#__APP_PRINCIPAL_ARN__#${APP_ARN}#g" \
      -e "s#__ADMIN_PRINCIPAL_ARN__#${ADMIN_ARN}#g" \
      -e "s#__APP_ORIGIN__#${APP_ORIGIN}#g" "$1"
}

if ! aws "${AWS_ARGS[@]}" s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  echo "==> Creating bucket $BUCKET"
  if [[ "$REGION" == "us-east-1" ]]; then
    aws "${AWS_ARGS[@]}" s3api create-bucket --bucket "$BUCKET"
  else
    aws "${AWS_ARGS[@]}" s3api create-bucket --bucket "$BUCKET" --create-bucket-configuration "LocationConstraint=$REGION"
  fi
fi

echo "==> Block Public Access: all on"
aws "${AWS_ARGS[@]}" s3api put-public-access-block --bucket "$BUCKET" \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

echo "==> ACLs disabled (bucket owner enforced)"
aws "${AWS_ARGS[@]}" s3api put-bucket-ownership-controls --bucket "$BUCKET" \
  --ownership-controls 'Rules=[{ObjectOwnership=BucketOwnerEnforced}]'

echo "==> Default encryption (SSE-S3)"
aws "${AWS_ARGS[@]}" s3api put-bucket-encryption --bucket "$BUCKET" \
  --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

echo "==> Bucket policy (TLS only; only $IAM_USER and $ADMIN_ARN allowed)"
render aws/job-bucket-policy.json > "$TMP_DIR/policy.json"
aws "${AWS_ARGS[@]}" s3api put-bucket-policy --bucket "$BUCKET" --policy "file://$TMP_DIR/policy.json"

echo "==> CORS (GET from $APP_ORIGIN only)"
render aws/job-bucket-cors.json > "$TMP_DIR/cors.json"
aws "${AWS_ARGS[@]}" s3api put-bucket-cors --bucket "$BUCKET" --cors-configuration "file://$TMP_DIR/cors.json"

echo "==> Verifying"
aws "${AWS_ARGS[@]}" s3api get-public-access-block --bucket "$BUCKET"
aws "${AWS_ARGS[@]}" s3api get-bucket-policy-status --bucket "$BUCKET" 2>/dev/null || echo "(no public policy -- good)"

KEY="jobs/_bucket-config-check.txt"
echo "private check" | aws "${AWS_ARGS[@]}" s3 cp - "s3://${BUCKET}/${KEY}" >/dev/null
STATUS="$(curl -s -o /dev/null -w '%{http_code}' "https://${BUCKET}.s3.${REGION}.amazonaws.com/${KEY}")"
aws "${AWS_ARGS[@]}" s3 rm "s3://${BUCKET}/${KEY}" >/dev/null
if [[ "$STATUS" != "403" ]]; then
  echo "ERROR: an anonymous GET returned HTTP $STATUS, expected 403 -- the bucket is not private." >&2
  exit 1
fi

echo "==> Done. Anonymous access is denied."
echo "    In backend/.env set JOB_STORAGE_S3_BUCKET=$BUCKET (and JOB_STORAGE_S3_REGION=$REGION if it differs from PUBLIC_ARCHIVE_S3_REGION),"
echo "    plus the job IAM user's keys. Its permissions come from configure-job-iam-user.sh, not this script."
