# apps/api/tests/services/storage/test_s3_provider.py

"""S3 storage provider tests."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from io import BytesIO
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from services.storage.copy_object import copy_object
from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.errors import (
    StoragePreconditionError,
    StorageProviderUnavailableError,
    StorageValidationError,
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


class _S3NoSuchCorsConfigurationError(Exception):
    def __init__(self) -> None:
        super().__init__("S3 bucket has no CORS configuration")
        self.response = {"Error": {"Code": "NoSuchCORSConfiguration"}}


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
        self.bucket_cors: dict[str, list[dict]] = {}

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

    def get_bucket_cors(self, **params) -> dict:
        try:
            rules = self.bucket_cors[params["Bucket"]]
        except KeyError as exc:
            raise _S3NoSuchCorsConfigurationError() from exc
        return {"CORSRules": [dict(rule) for rule in rules]}

    def put_bucket_cors(self, **params) -> None:
        rules = params["CORSConfiguration"]["CORSRules"]
        self.bucket_configuration.setdefault(params["Bucket"], {}).update(params)
        self.bucket_cors[params["Bucket"]] = [dict(rule) for rule in rules]

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
        platform_private_bucket="platform-private",
        workspace_bucket_prefix="praxis-test",
        region_name=AWS_REGION,
        account_id=AWS_ACCOUNT_ID,
        public_assets_base_url="https://cdn.example",
        cors_origins=("https://app.example", "https://admin.example/"),
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


@pytest.mark.parametrize("bucket", [StorageBucket.PLATFORM_PRIVATE])
async def test_s3_promotion_is_create_only_and_source_conditional(bucket: StorageBucket) -> None:
    client = _FakeS3Client()
    provider = _provider(client)
    prefix = (
        "platform" if bucket == StorageBucket.PLATFORM_PRIVATE else f"workspaces/{WORKSPACE_ID}"
    )
    source = make_storage_object_ref(bucket, f"{prefix}/uploads/source.txt")
    destination = make_storage_object_ref(bucket, f"{prefix}/files/final.txt")
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
    assert config["CORSConfiguration"] == {
        "CORSRules": [
            {
                "ID": "PraxisBrowserSignedUploads",
                "AllowedOrigins": ["https://app.example", "https://admin.example"],
                "AllowedMethods": ["GET", "HEAD", "PUT"],
                "AllowedHeaders": ["Content-Length", "Content-Type", "If-None-Match"],
                "ExposeHeaders": ["Content-Length", "Content-Type", "ETag"],
                "MaxAgeSeconds": 3600,
            }
        ]
    }
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


async def test_s3_public_upload_converges_cors_once_and_preserves_other_rules() -> None:
    client = _FakeS3Client()
    client.bucket_cors["public-bucket"] = [
        {
            "ID": "OperatorManagedDownload",
            "AllowedOrigins": ["https://reports.example"],
            "AllowedMethods": ["GET"],
        }
    ]
    provider = _provider(client)
    first_ref = make_storage_object_ref(StorageBucket.PUBLIC, "users/u_1/avatar/one.png")
    second_ref = make_storage_object_ref(StorageBucket.PUBLIC, "users/u_1/avatar/two.png")

    await provider.create_signed_upload(
        first_ref,
        content_type="image/png",
        expected_size_bytes=3,
        expires_in=timedelta(minutes=5),
    )
    first_rules = [dict(rule) for rule in client.bucket_cors["public-bucket"]]
    await provider.create_signed_upload(
        second_ref,
        content_type="image/png",
        expected_size_bytes=3,
        expires_in=timedelta(minutes=5),
    )

    assert client.bucket_cors["public-bucket"] == first_rules
    assert first_rules[0]["ID"] == "OperatorManagedDownload"
    assert first_rules[1]["ID"] == "PraxisBrowserSignedUploads"


async def test_s3_platform_objects_remain_private_and_sign_in_the_platform_bucket() -> None:
    client = _FakeS3Client()
    provider = _provider(client)
    ref = make_storage_object_ref(StorageBucket.PLATFORM_PRIVATE, "platform/files/report.txt")
    stored = await provider.put_object(ref, b"report", content_type="text/plain", overwrite=False)
    assert stored.public_url is None
    assert stored.cache_control is None
    assert provider.public_url(ref) is None
    assert await provider.get_object(ref) == b"report"
    assert b"".join([chunk async for chunk in provider.stream_object(ref)]) == b"report"
    with pytest.raises(StoragePreconditionError):
        await provider.put_object(ref, b"replace", overwrite=False)
    upload = await provider.create_signed_upload(
        ref, content_type="text/plain", expected_size_bytes=6, expires_in=timedelta(minutes=5)
    )
    download = await provider.create_signed_download(ref, expires_in=timedelta(minutes=5))
    assert upload.ref == ref
    assert download.ref == ref
    assert all(call["Params"]["Bucket"] == "platform-private" for call in client.presigned_calls)
    assert ("platform-private", ref.key) in client.objects
    assert set(client.bucket_configuration) == {"platform-private"}
    assert set(client.bucket_cors) == {"platform-private"}
    assert await provider.delete_object(ref) is True
    assert await provider.stat_object(ref) is None
    assert await provider.delete_object(ref) is False


@pytest.mark.parametrize("configured_name", ["public-bucket", WORKSPACE_BUCKET])
async def test_s3_platform_objects_reject_missing_or_public_bucket(configured_name: str) -> None:
    provider = _provider(_FakeS3Client())
    provider.platform_private_bucket = configured_name
    ref = make_storage_object_ref(StorageBucket.PLATFORM_PRIVATE, "platform/files/report.txt")
    with pytest.raises((StorageProviderUnavailableError, StorageValidationError)):
        await provider.put_object(ref, b"report")
    for operation in (provider.get_object, provider.stat_object, provider.delete_object):
        with pytest.raises((StorageProviderUnavailableError, StorageValidationError)):
            await operation(ref)
    with pytest.raises((StorageProviderUnavailableError, StorageValidationError)):
        _ = [chunk async for chunk in provider.stream_object(ref)]
    with pytest.raises((StorageProviderUnavailableError, StorageValidationError)):
        await provider.create_signed_download(ref, expires_in=timedelta(minutes=5))
    destination = make_storage_object_ref(
        StorageBucket.PLATFORM_PRIVATE, "platform/files/final.txt"
    )
    with pytest.raises((StorageProviderUnavailableError, StorageValidationError)):
        await provider.promote_object(ref, destination, expected_source_etag="etag")
    with pytest.raises((StorageProviderUnavailableError, StorageValidationError)):
        await provider.create_signed_upload(
            ref, content_type="text/plain", expected_size_bytes=6, expires_in=timedelta(minutes=5)
        )


@pytest.mark.parametrize(
    ("bucket", "key"),
    [
        (StorageBucket.PLATFORM_PRIVATE, _private_key("files/report.txt")),
        (StorageBucket.PRIVATE, "platform/files/report.txt"),
    ],
)
async def test_s3_rejects_namespace_substitution(bucket: StorageBucket, key: str) -> None:
    provider = _provider(_FakeS3Client())
    ref = make_storage_object_ref(bucket, key)
    with pytest.raises(StorageValidationError):
        await provider.put_object(ref, b"report")
    with pytest.raises(StorageValidationError):
        await provider.get_object(ref)
    with pytest.raises(StorageValidationError):
        await provider.stat_object(ref)
    with pytest.raises(StorageValidationError):
        await provider.delete_object(ref)
    with pytest.raises(StorageValidationError):
        _ = [chunk async for chunk in provider.stream_object(ref)]
    valid = make_storage_object_ref(StorageBucket.PLATFORM_PRIVATE, "platform/files/valid.txt")
    with pytest.raises(StorageValidationError):
        await provider.promote_object(ref, valid, expected_source_etag="etag")
    with pytest.raises(StorageValidationError):
        await provider.promote_object(valid, ref, expected_source_etag="etag")
    with pytest.raises(StorageValidationError):
        await provider.create_signed_upload(
            ref, content_type="text/plain", expected_size_bytes=6, expires_in=timedelta(minutes=5)
        )
    with pytest.raises(StorageValidationError):
        await provider.create_signed_download(ref, expires_in=timedelta(minutes=5))


@pytest.mark.parametrize("source_bucket", [StorageBucket.PRIVATE])
async def test_s3_platform_cross_class_copy_is_immutable_and_retryable(source_bucket) -> None:
    client = _FakeS3Client()
    provider = _provider(client)
    workspace_ref = make_storage_object_ref(StorageBucket.PRIVATE, _private_key("files/copy.txt"))
    platform_ref = make_storage_object_ref(
        StorageBucket.PLATFORM_PRIVATE, "platform/files/copy.txt"
    )
    source, destination = (
        (workspace_ref, platform_ref)
        if source_bucket == StorageBucket.PRIVATE
        else (platform_ref, workspace_ref)
    )
    await provider.put_object(
        source, b"report", content_type="text/plain", metadata={"private_owner": "internal"}
    )
    authorise = AsyncMock()
    arguments = {
        "authorise": authorise,
        "expected_size_bytes": 6,
        "expected_sha256": hashlib.sha256(b"report").hexdigest(),
        "content_type": "text/plain",
    }
    copied = await copy_object(provider, source, destination, **arguments)
    retried = await copy_object(provider, source, destination, **arguments)
    assert copied == retried
    assert copied.metadata == {}
    assert copied.cache_control == "private, no-store"
    assert await provider.get_object(destination) == b"report"
    assert await provider.get_object(source) == b"report"
    assert authorise.await_count == 3
    assert all("copy-staging/" not in key for _, key in client.objects)
