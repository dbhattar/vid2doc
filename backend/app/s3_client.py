"""Single place boto3 is configured for the permanent public-showcase
archive (see app/public_jobs.py). Unlike stripe_client.py/mailgun_client.py,
credentials are NOT read through Settings -- they come from boto3's own
default credential chain (AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY env vars
for local dev, or an attached IAM role/instance profile in production),
which is the standard, more secure way to run boto3 in a real deployment.
Only the bucket/region (which aren't secrets) come from Settings."""

import boto3

from .config import settings


def get_client():
    return boto3.client("s3", region_name=settings.PUBLIC_ARCHIVE_S3_REGION)


__all__ = ["get_client"]
