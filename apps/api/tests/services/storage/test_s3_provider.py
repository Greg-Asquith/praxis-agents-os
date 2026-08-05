# apps/api/tests/services/storage/test_s3_provider.py

"""S3 storage provider tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import UUID

import pytest

from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.errors import (
    StorageNotFoundError,
    StoragePreconditionError,
    StorageProviderUnavailableError,
)
from services.storage.providers.s3 import S3StorageProvider
from services.storage.workspace_buckets import s3_workspace_bucket_name

pytestmark = pytest.mark.asyncio
WORKSPACE_ID = UUID("11111111-1111-4111-8111-111111111111")
AWS_ACCOUNT_ID = "123456789012"
AWS_REGION = "eu-west-2"
WORKSPACE_BUCKET = s3_workspace_bucket_name(
    "praxis-test",
    WORKSPACE_ID,
    account_id=AWS_ACCOUNT_ID,
    region=AWS_REGION,
)


def _private_key(suffix: str) -> str:
    return f"workspaces/{WORKSPACE_ID}/{suffix}"


class _S3NotFoundError(Exception):
    def __init__(self) -> None:
        super().__init__("S3 object not found")
        self.response = {"Error": {"Code": "NoSuchKey"}}


class _S3PreconditionError(Exception):
    def __init__(self) -> None:
        super().__init__("S3 precondition failed")
        self.response = {
            "Error": {"Code": "PreconditionFailed"},
            "ResponseMetadata": {"HTTPStatusCode": 412},
        }


class _S3NoSuchTagSetError(Exception):
    def __init__(self) -> None:
        super().__init__("S3 bucket has no tags")
        self.response = {"Error": {"Code": "NoSuchTagSet"}}


class _S3NoSuchBucketPolicyError(Exception):
    def __init__(self) -> None:
        super().__init__("S3 bucket has no policy")
        self.response = {"Error": {"Code": "NoSuchBucketPolicy"}}


class _FakeBody(BytesIO):
    closed_by_provider = False

    def close(self) -> None:
        self.closed_by_provider = True
        super().close()


class _FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], dict] = {}
        self.presigned_calls: list[dict] = []
        self.deleted: list[tuple[str, str]] = []
        self.buckets = {"public-bucket"}
        self.bucket_configuration: dict[str, dict] = {}
        self.bucket_tags: dict[str, list[dict[str, str]]] = {}
        self.bucket_policies: dict[str, dict] = {}

    def head_bucket(self, **params) -> None:
        if params["Bucket"] not in self.buckets:
            raise _S3NotFoundError()

    def create_bucket(self, **params) -> None:
        self.bucket_configuration.setdefault(params["Bucket"], {}).update({"CreateBucket": params})
        self.buckets.add(params["Bucket"])

    def put_public_access_block(self, **params) -> None:
        self.bucket_configuration.setdefault(params["Bucket"], {}).update(params)

    def put_bucket_encryption(self, **params) -> None:
        self.bucket_configuration.setdefault(params["Bucket"], {}).update(params)

    def put_bucket_ownership_controls(self, **params) -> None:
        self.bucket_configuration.setdefault(params["Bucket"], {}).update(params)

    def put_bucket_versioning(self, **params) -> None:
        self.bucket_configuration.setdefault(params["Bucket"], {}).update(params)

    def get_bucket_policy(self, **params) -> dict:
        try:
            policy = self.bucket_policies[params["Bucket"]]
        except KeyError as exc:
            raise _S3NoSuchBucketPolicyError() from exc
        return {"Policy": json.dumps(policy)}

    def put_bucket_policy(self, **params) -> None:
        policy = json.loads(params["Policy"])
        self.bucket_configuration.setdefault(params["Bucket"], {}).update({"Policy": policy})
        self.bucket_policies[params["Bucket"]] = policy

    def get_bucket_tagging(self, **params) -> dict:
        try:
            tags = self.bucket_tags[params["Bucket"]]
        except KeyError as exc:
            raise _S3NoSuchTagSetError() from exc
        return {"TagSet": [dict(tag) for tag in tags]}

    def put_bucket_tagging(self, **params) -> None:
        self.bucket_configuration.setdefault(params["Bucket"], {}).update(params)
        self.bucket_tags[params["Bucket"]] = [dict(tag) for tag in params["Tagging"]["TagSet"]]

    def put_object(self, **params):
        key = (params["Bucket"], params["Key"])
        if params.get("IfNoneMatch") == "*" and key in self.objects:
            raise _S3PreconditionError()
        self.objects[key] = {
            "body": params["Body"],
            "content_type": params.get("ContentType"),
            "cache_control": params.get("CacheControl"),
            "metadata": params.get("Metadata") or {},
            "etag": '"etag-1"',
            "last_modified": datetime(2026, 7, 1, tzinfo=UTC),
        }

    def head_object(self, **kwargs):
        bucket = kwargs["Bucket"]
        key = kwargs["Key"]
        obj = self.objects.get((bucket, key))
        if obj is None:
            raise _S3NotFoundError()
        return {
            "ContentLength": len(obj["body"]),
            "ContentType": obj["content_type"],
            "CacheControl": obj["cache_control"],
            "Metadata": obj["metadata"],
            "ETag": obj["etag"],
            "LastModified": obj["last_modified"],
        }

    def get_object(self, **kwargs):
        bucket = kwargs["Bucket"]
        key = kwargs["Key"]
        obj = self.objects.get((bucket, key))
        if obj is None:
            raise _S3NotFoundError()
        return {"Body": _FakeBody(obj["body"])}

    def delete_object(self, **kwargs):
        bucket = kwargs["Bucket"]
        key = kwargs["Key"]
        self.objects.pop((bucket, key), None)
        self.deleted.append((bucket, key))

    def copy_object(self, **params):
        source = (params["CopySource"]["Bucket"], params["CopySource"]["Key"])
        destination = (params["Bucket"], params["Key"])
        source_obj = self.objects.get(source)
        if source_obj is None:
            raise _S3NotFoundError()
        if params.get("IfNoneMatch") == "*" and destination in self.objects:
            raise _S3PreconditionError()
        if source_obj["etag"].strip('"') != params.get("CopySourceIfMatch", "").strip('"'):
            raise _S3PreconditionError()
        self.objects[destination] = dict(source_obj)

    def generate_presigned_url(self, operation: str, **kwargs):
        self.presigned_calls.append({"operation": operation, **kwargs})
        return f"https://signed.example/{operation}/{kwargs['Params']['Key']}"


def _provider(client: _FakeS3Client) -> S3StorageProvider:
    return S3StorageProvider(
        public_bucket_name="public-bucket",
        workspace_bucket_prefix="praxis-test",
        region_name=AWS_REGION,
        account_id=AWS_ACCOUNT_ID,
        public_assets_base_url="https://cdn.example",
        public_cache_control="public, max-age=60",
        client=client,
    )


async def test_s3_provider_put_get_stat_and_delete_object() -> None:
    client = _FakeS3Client()
    provider = _provider(client)
    ref = make_storage_object_ref(StorageBucket.PUBLIC, "users/u_1/avatar/me.png")

    stored = await provider.put_object(
        ref,
        b"png",
        content_type="image/png",
        metadata={"purpose": "avatar"},
    )

    assert client.objects[("public-bucket", ref.key)]["cache_control"] == "public, max-age=60"
    assert stored.size_bytes == 3
    assert stored.etag == "etag-1"
    assert stored.content_type == "image/png"
    assert stored.metadata == {"purpose": "avatar"}
    assert stored.public_url == "https://cdn.example/users/u_1/avatar/me.png"
    assert await provider.get_object(ref) == b"png"

    assert await provider.delete_object(ref) is True
    assert await provider.stat_object(ref) is None
    assert await provider.delete_object(ref) is False


async def test_s3_provider_maps_get_not_found_to_storage_error() -> None:
    provider = _provider(_FakeS3Client())
    ref = make_storage_object_ref(StorageBucket.PRIVATE, _private_key("missing.txt"))

    with pytest.raises(StorageNotFoundError):
        await provider.get_object(ref)

    assert await provider.stat_object(ref) is None


async def test_s3_provider_signed_urls_bind_content_type_and_disposition() -> None:
    client = _FakeS3Client()
    provider = _provider(client)
    ref = make_storage_object_ref(StorageBucket.PRIVATE, _private_key("output.txt"))

    upload = await provider.create_signed_upload(
        ref,
        content_type="text/plain",
        expected_size_bytes=4,
        expires_in=timedelta(minutes=5),
    )
    download = await provider.create_signed_download(
        ref,
        expires_in=timedelta(minutes=5),
        force_download=True,
        filename="output.txt",
    )

    assert upload.headers == {"content-type": "text/plain", "if-none-match": "*"}
    assert client.presigned_calls[0]["operation"] == "put_object"
    assert client.presigned_calls[0]["Params"]["ContentType"] == "text/plain"
    assert client.presigned_calls[0]["Params"]["ContentLength"] == 4
    assert client.presigned_calls[0]["Params"]["IfNoneMatch"] == "*"
    assert download.headers == {"content-disposition": 'attachment; filename="output.txt"'}
    assert client.presigned_calls[1]["operation"] == "get_object"
    assert (
        client.presigned_calls[1]["Params"]["ResponseContentDisposition"]
        == 'attachment; filename="output.txt"'
    )


async def test_s3_public_signed_download_returns_public_url() -> None:
    provider = _provider(_FakeS3Client())
    ref = make_storage_object_ref(StorageBucket.PUBLIC, "users/u_1/avatar/me.png")

    download = await provider.create_signed_download(ref, expires_in=timedelta(minutes=5))

    assert download.url == "https://cdn.example/users/u_1/avatar/me.png"


async def test_s3_promotion_is_create_only_and_source_conditional() -> None:
    client = _FakeS3Client()
    provider = _provider(client)
    source = make_storage_object_ref(StorageBucket.PRIVATE, _private_key("uploads/source.txt"))
    destination = make_storage_object_ref(StorageBucket.PRIVATE, _private_key("files/final.txt"))
    source_stored = await provider.put_object(source, b"validated", content_type="text/plain")

    promoted = await provider.promote_object(
        source,
        destination,
        expected_source_etag=source_stored.etag,
    )

    assert await provider.get_object(destination) == b"validated"
    assert promoted.content_type == "text/plain"
    with pytest.raises(StoragePreconditionError):
        await provider.promote_object(
            source,
            destination,
            expected_source_etag=source_stored.etag,
        )


async def test_s3_provider_missing_required_settings_fail_clearly() -> None:
    with pytest.raises(StorageProviderUnavailableError):
        S3StorageProvider(
            public_bucket_name="",
            workspace_bucket_prefix="praxis-test",
            region_name=AWS_REGION,
            account_id=AWS_ACCOUNT_ID,
            public_assets_base_url="https://cdn.example",
            client=_FakeS3Client(),
        )


async def test_s3_workspace_bucket_is_hardened_and_signed_urls_are_confined() -> None:
    client = _FakeS3Client()
    provider = _provider(client)
    ref = make_storage_object_ref(StorageBucket.PRIVATE, _private_key("files/report.txt"))

    await provider.ensure_workspace_bucket(WORKSPACE_ID)
    await provider.ensure_workspace_bucket(WORKSPACE_ID)
    signed = await provider.create_signed_upload(
        ref,
        content_type="text/plain",
        expected_size_bytes=4,
        expires_in=timedelta(minutes=5),
    )

    config = client.bucket_configuration[WORKSPACE_BUCKET]
    assert config["CreateBucket"] == {
        "Bucket": WORKSPACE_BUCKET,
        "BucketNamespace": "account-regional",
        "ObjectOwnership": "BucketOwnerEnforced",
        "CreateBucketConfiguration": {"LocationConstraint": AWS_REGION},
    }
    assert config["PublicAccessBlockConfiguration"] == {
        "BlockPublicAcls": True,
        "IgnorePublicAcls": True,
        "BlockPublicPolicy": True,
        "RestrictPublicBuckets": True,
    }
    assert config["ServerSideEncryptionConfiguration"] == {
        "Rules": [
            {
                "ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"},
                "BucketKeyEnabled": True,
                "BlockedEncryptionTypes": {"EncryptionType": ["SSE-C"]},
            }
        ]
    }
    assert config["OwnershipControls"] == {"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]}
    assert config["VersioningConfiguration"] == {"Status": "Enabled"}
    assert config["Policy"]["Statement"] == [
        {
            "Sid": "DenyInsecureTransport",
            "Effect": "Deny",
            "Principal": "*",
            "Action": "s3:*",
            "Resource": [
                f"arn:aws:s3:::{WORKSPACE_BUCKET}",
                f"arn:aws:s3:::{WORKSPACE_BUCKET}/*",
            ],
            "Condition": {"Bool": {"aws:SecureTransport": "false"}},
        }
    ]
    assert config["Tagging"]["TagSet"] == [{"Key": "praxis-workspace", "Value": str(WORKSPACE_ID)}]
    assert client.presigned_calls[-1]["Params"]["Bucket"] == WORKSPACE_BUCKET
    assert signed.ref == ref


async def test_s3_workspace_bucket_provisioning_preserves_existing_tags() -> None:
    client = _FakeS3Client()
    client.buckets.add(WORKSPACE_BUCKET)
    client.bucket_tags[WORKSPACE_BUCKET] = [
        {"Key": "environment", "Value": "staging"},
        {"Key": "praxis-workspace", "Value": "stale"},
    ]
    provider = _provider(client)

    await provider.ensure_workspace_bucket(WORKSPACE_ID)

    assert client.bucket_tags[WORKSPACE_BUCKET] == [
        {"Key": "environment", "Value": "staging"},
        {"Key": "praxis-workspace", "Value": str(WORKSPACE_ID)},
    ]


async def test_s3_workspace_bucket_provisioning_preserves_existing_policy_statements() -> None:
    client = _FakeS3Client()
    client.buckets.add(WORKSPACE_BUCKET)
    existing_statement = {
        "Sid": "OperatorPolicy",
        "Effect": "Deny",
        "Principal": "*",
        "Action": "s3:DeleteBucket",
        "Resource": f"arn:aws:s3:::{WORKSPACE_BUCKET}",
    }
    client.bucket_policies[WORKSPACE_BUCKET] = {
        "Version": "2012-10-17",
        "Statement": [existing_statement],
    }
    provider = _provider(client)

    await provider.ensure_workspace_bucket(WORKSPACE_ID)

    assert client.bucket_policies[WORKSPACE_BUCKET]["Statement"][0] == existing_statement
    assert client.bucket_policies[WORKSPACE_BUCKET]["Statement"][1]["Sid"] == (
        "DenyInsecureTransport"
    )
