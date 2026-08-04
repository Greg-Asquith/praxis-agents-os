# apps/api/core/storage_buckets.py

"""Provider-neutral workspace bucket naming constraints."""

LOCAL_WORKSPACE_BUCKET_PREFIX = "praxis-local"
WORKSPACE_BUCKET_PREFIX_MAX_LENGTH = 26
S3_ACCOUNT_REGIONAL_UNSUPPORTED_REGIONS = frozenset({"me-central-1", "me-south-1"})


def s3_workspace_bucket_prefix_max_length(region: str) -> int:
    """Return the prefix capacity for a base36 UUID plus the account-regional suffix."""
    return 63 - 43 - len(region)
