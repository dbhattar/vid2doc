#!/usr/bin/env bash
# Sets up the IAM user the app uses for the private job-storage buckets (see
# backend/app/job_storage.py): creates the user if it doesn't exist (with
# --create-user) and attaches the inline policy in aws/job-bucket-user-access.json,
# which allows object access under jobs/* (plus listing that prefix) in the
# given buckets -- by default framewrite-jobs-dev and framewrite-jobs-prod -- and
# nothing else. It is a separate identity from the one in backend/.env's
# AWS_ACCESS_KEY_ID, which owns the public showcase bucket; the app reads this
# one from JOB_STORAGE_AWS_ACCESS_KEY_ID / JOB_STORAGE_AWS_SECRET_ACCESS_KEY.
#
# Run this BEFORE configure-job-bucket.sh: that script allows this user in each
# bucket's policy and so needs it to exist. The buckets themselves don't need to
# exist yet for the policy to be attached.
#
# Usage:
#   ./configure-job-iam-user.sh --profile framewrite-admin --iam-user framewrite-jobs --create-user
#
#   # Only one bucket, or different names:
#   ./configure-job-iam-user.sh --profile framewrite-admin --iam-user framewrite-jobs \
#       --buckets framewrite-jobs-prod
#
#   # Also create an access key and print it ONCE (put it in backend/.env):
#   ./configure-job-iam-user.sh --profile framewrite-admin --iam-user framewrite-jobs --create-access-key
#
# Re-running is safe: the policy is replaced with the current one (so --buckets
# must list every bucket the user should reach, not just a new one).
# --profile needs iam:GetUser, iam:PutUserPolicy and, for the optional steps,
# iam:CreateUser, iam:CreateAccessKey/ListAccessKeys and iam:SimulatePrincipalPolicy.
# It should be an admin identity, not this user.

set -euo pipefail
cd "$(dirname "$0")"

PROFILE="" IAM_USER="" BUCKETS="framewrite-jobs-dev,framewrite-jobs-prod" CREATE_USER=false CREATE_KEY=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile) PROFILE="$2"; shift 2 ;;
    --iam-user) IAM_USER="$2"; shift 2 ;;
    --buckets) BUCKETS="$2"; shift 2 ;;
    --create-user) CREATE_USER=true; shift ;;
    --create-access-key) CREATE_KEY=true; shift ;;
    *) echo "ERROR: unknown argument: $1" >&2; exit 1 ;;
  esac
done
if [[ -z "$PROFILE" || -z "$IAM_USER" ]]; then
  echo "Usage: $0 --profile <aws-profile> --iam-user <name> [--buckets b1,b2] [--create-user] [--create-access-key]" >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 is needed to build the policy from --buckets." >&2
  exit 1
fi

IFS=',' read -r -a BUCKET_LIST <<< "$BUCKETS"
for b in "${BUCKET_LIST[@]}"; do
  if [[ ! "$b" =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ ]]; then
    echo "ERROR: '$b' isn't a valid S3 bucket name (lowercase letters, digits, dots, hyphens; 3-63 chars)." >&2
    exit 1
  fi
done

AWS_ARGS=(--profile "$PROFILE")
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

if aws "${AWS_ARGS[@]}" iam get-user --user-name "$IAM_USER" >/dev/null 2>&1; then
  echo "==> IAM user '$IAM_USER' exists"
elif [[ "$CREATE_USER" == true ]]; then
  echo "==> Creating IAM user '$IAM_USER'"
  aws "${AWS_ARGS[@]}" iam create-user --user-name "$IAM_USER" >/dev/null
else
  echo "ERROR: IAM user '$IAM_USER' not found (or this profile can't read it). Pass --create-user to create it." >&2
  exit 1
fi
USER_ARN="$(aws "${AWS_ARGS[@]}" iam get-user --user-name "$IAM_USER" --query User.Arn --output text)"

# The checked-in template names the dev and prod buckets; swap in --buckets so
# the same file serves any set of buckets.
python3 - aws/job-bucket-user-access.json "$BUCKETS" > "$TMP_DIR/policy.json" <<'PY'
import json, sys
policy = json.load(open(sys.argv[1]))
buckets = [b for b in sys.argv[2].split(",") if b]
for statement in policy["Statement"]:
    if statement["Sid"] == "FramewriteJobStorageObjectAccess":
        statement["Resource"] = [f"arn:aws:s3:::{b}/jobs/*" for b in buckets]
    elif statement["Sid"] == "FramewriteJobStorageList":
        statement["Resource"] = [f"arn:aws:s3:::{b}" for b in buckets]
print(json.dumps(policy, indent=2))
PY

echo "==> Attaching policy FramewriteJobStorageAccess to '$IAM_USER' for: ${BUCKET_LIST[*]}"
aws "${AWS_ARGS[@]}" iam put-user-policy --user-name "$IAM_USER" \
  --policy-name FramewriteJobStorageAccess --policy-document "file://$TMP_DIR/policy.json"

echo "==> Verifying with the policy simulator (best effort)"
for b in "${BUCKET_LIST[@]}"; do
  ALLOWED="$(aws "${AWS_ARGS[@]}" iam simulate-principal-policy --policy-source-arn "$USER_ARN" \
    --action-names s3:PutObject s3:GetObject s3:DeleteObject \
    --resource-arns "arn:aws:s3:::${b}/jobs/_check" \
    --query 'EvaluationResults[].EvalDecision' --output text 2>/dev/null || true)"
  OUTSIDE="$(aws "${AWS_ARGS[@]}" iam simulate-principal-policy --policy-source-arn "$USER_ARN" \
    --action-names s3:GetObject \
    --resource-arns "arn:aws:s3:::${b}/public/_check" \
    --query 'EvaluationResults[].EvalDecision' --output text 2>/dev/null || true)"
  if [[ -z "$ALLOWED" ]]; then
    echo "    $b: couldn't run the simulator (needs iam:SimulatePrincipalPolicy) -- skipped"
  elif [[ "$ALLOWED" == "allowed allowed allowed" && "$OUTSIDE" != "allowed" ]]; then
    echo "    $b: jobs/* put/get/delete allowed, other prefixes not -- OK"
  else
    echo "ERROR: $b: unexpected result (jobs/*: $ALLOWED; outside jobs/*: $OUTSIDE)" >&2
    exit 1
  fi
done

if [[ "$CREATE_KEY" == true ]]; then
  KEY_COUNT="$(aws "${AWS_ARGS[@]}" iam list-access-keys --user-name "$IAM_USER" --query 'length(AccessKeyMetadata)' --output text)"
  if [[ "$KEY_COUNT" -ge 2 ]]; then
    echo "ERROR: '$IAM_USER' already has $KEY_COUNT access keys (the AWS limit is 2). Delete one first:" >&2
    echo "       aws --profile $PROFILE iam delete-access-key --user-name $IAM_USER --access-key-id <id>" >&2
    exit 1
  fi
  echo "==> Creating an access key -- the secret is shown ONCE, copy it into backend/.env now"
  aws "${AWS_ARGS[@]}" iam create-access-key --user-name "$IAM_USER" \
    --query 'AccessKey.[AccessKeyId,SecretAccessKey]' --output text |
    awk '{ print "JOB_STORAGE_AWS_ACCESS_KEY_ID=" $1; print "JOB_STORAGE_AWS_SECRET_ACCESS_KEY=" $2 }'
fi

echo "==> Done. Next, for each bucket: ./configure-job-bucket.sh --iam-user $IAM_USER ... (see README.md)"
