"""Single place boto3 is configured: one client for the permanent public-
showcase archive (see app/public_jobs.py) and one for the private job-storage
bucket (see app/job_storage.py).

The showcase client takes its credentials from boto3's own default chain
(AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY env vars, or an attached IAM
role/instance profile) -- the standard, more secure way to run boto3. The job
client uses a separate IAM user so that identity can reach only the job bucket
(and the showcase user only the showcase bucket): its keys come from
JOB_STORAGE_AWS_ACCESS_KEY_ID/JOB_STORAGE_AWS_SECRET_ACCESS_KEY, or from the
default chain when those are empty. Only the buckets/regions (which aren't
secrets) otherwise come from Settings."""

import boto3

from .config import settings


def get_client():
    """Showcase bucket (PUBLIC_ARCHIVE_S3_BUCKET)."""
    return boto3.client("s3", region_name=settings.PUBLIC_ARCHIVE_S3_REGION)


def get_job_client():
    """Private job-storage bucket (JOB_STORAGE_S3_BUCKET), as its own IAM user."""
    kwargs = {}
    if settings.JOB_STORAGE_AWS_ACCESS_KEY_ID and settings.JOB_STORAGE_AWS_SECRET_ACCESS_KEY:
        kwargs = {
            "aws_access_key_id": settings.JOB_STORAGE_AWS_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.JOB_STORAGE_AWS_SECRET_ACCESS_KEY,
        }
    return boto3.client("s3", region_name=settings.JOB_STORAGE_S3_REGION, **kwargs)


__all__ = ["get_client", "get_job_client"]
