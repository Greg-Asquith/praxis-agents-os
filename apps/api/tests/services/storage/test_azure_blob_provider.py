# apps/api/tests/services/storage/test_azure_blob_provider.py

"""Azure Blob storage provider tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest

from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.errors import (
    StoragePreconditionError,
    StorageSignatureError,
)
from services.storage.providers import azure_blob as azure_blob_provider_module
from services.storage.providers.azure_blob import AzureBlobStorageProvider

pytestmark = pytest.mark.asyncio
WORKSPACE_ID = UUID("11111111-1111-4111-8111-111111111111")
WORKSPACE_CONTAINER = f"praxis-test-{WORKSPACE_ID}"


def _private_key(suffix: str) -> str:
    return f"workspaces/{WORKSPACE_ID}/{suffix}"


class _AzureNotFoundError(Exception):
    error_code = "BlobNotFound"


class _AzurePreconditionError(Exception):
    error_code = "BlobAlreadyExists"
    status_code = 409


class _FakeMatchConditions:
    IfNotModified = "if_not_modified"


class _FakeContentSettings:
    def __init__(
        self,
        *,
        content_type: str | None = None,
        cache_control: str | None = None,
    ) -> None:
        self.content_type = content_type
        self.cache_control = cache_control


class _FakePermissions:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs


class _FakeDownload:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def readall(self) -> bytes:
        return self.data


class _FakeProperties:
    def __init__(self, obj: dict) -> None:
        self.size = len(obj["data"])
        self.content_settings = obj["content_settings"]
        self.metadata = obj["metadata"]
        self.etag = "azure-etag"
        self.last_modified = datetime(2026, 7, 1, tzinfo=UTC)


class _FakeBlobClient:
    def __init__(self, container: _FakeContainer, key: str) -> None:
        self.container = container
        self.key = key

    def upload_blob(
        self,
        data: bytes,
        *,
        overwrite: bool,
        content_settings,
        metadata: dict[str, str] | None = None,
    ) -> None:
        if not overwrite and self.key in self.container.objects:
            raise _AzurePreconditionError()
        self.container.objects[self.key] = {
            "data": data,
            "content_settings": content_settings,
            "metadata": metadata or {},
            "overwrite": overwrite,
        }

    def exists(self) -> bool:
        return self.key in self.container.objects

    def download_blob(self, **kwargs) -> _FakeDownload:
        if kwargs and kwargs.get("etag") != "azure-etag":
            raise _AzurePreconditionError()
        return _FakeDownload(self.container.objects[self.key]["data"])

    def get_blob_properties(self) -> _FakeProperties:
        obj = self.container.objects.get(self.key)
        if obj is None:
            raise _AzureNotFoundError()
        return _FakeProperties(obj)

    def delete_blob(self, *, delete_snapshots: str) -> None:
        assert delete_snapshots == "include"
        self.container.objects.pop(self.key, None)


class _FakeContainer:
    def __init__(self, service: _FakeBlobServiceClient, name: str) -> None:
        self.service = service
        self.name = name
        self.container_name = name
        self.objects: dict[str, dict] = {}
        self.metadata: dict[str, str] = {}
        self.public_access = "container"
        self.signed_identifiers: dict = {}

    def get_blob_client(self, key: str) -> _FakeBlobClient:
        return _FakeBlobClient(self, key)

    def get_container_properties(self) -> dict:
        if self.name not in self.service.existing_containers:
            raise _AzureNotFoundError()
        return {"metadata": self.metadata}

    def create_container(self, *, metadata: dict[str, str]) -> None:
        if self.name in self.service.existing_containers:
            raise _AzurePreconditionError()
        self.service.existing_containers.add(self.name)
        self.metadata = metadata

    def set_container_metadata(self, *, metadata: dict[str, str]) -> None:
        self.metadata = metadata

    def get_container_access_policy(self) -> dict:
        return {
            "public_access": self.public_access,
            "signed_identifiers": dict(self.signed_identifiers),
        }

    def set_container_access_policy(self, *, signed_identifiers: dict, public_access) -> None:
        self.signed_identifiers = dict(signed_identifiers)
        self.public_access = public_access


class _FakeBlobServiceClient:
    def __init__(self) -> None:
        self.containers: dict[str, _FakeContainer] = {}
        self.existing_containers = {"public"}
        self.delegation_key_calls = 0

    def get_container_client(self, name: str) -> _FakeContainer:
        self.containers.setdefault(name, _FakeContainer(self, name))
        return self.containers[name]

    def get_user_delegation_key(self, _starts_on, _expires_on):
        self.delegation_key_calls += 1
        return "delegation-key"


def _fake_generate_blob_sas(**kwargs) -> str:
    _fake_generate_blob_sas.calls.append(kwargs)
    return "sv=fake"


_fake_generate_blob_sas.calls = []


def _provider(service_client: _FakeBlobServiceClient) -> AzureBlobStorageProvider:
    _fake_generate_blob_sas.calls.clear()
    return AzureBlobStorageProvider(
        account_name="storageacct",
        public_container_name="public",
        platform_private_container="platform-private",
        workspace_bucket_prefix="praxis-test",
        app_base_url="http://testserver",
        api_prefix="/api/v1",
        secret_key="s" * 32,
        account_url="https://storageacct.blob.core.windows.net",
        public_assets_base_url="https://cdn.example",
        public_cache_control="public, max-age=60",
        credential=object(),
        service_client=service_client,
        content_settings_cls=_FakeContentSettings,
        match_conditions_cls=_FakeMatchConditions,
        sas_permissions_cls=_FakePermissions,
        generate_sas_func=_fake_generate_blob_sas,
    )


async def test_azure_blob_uses_size_bound_upload_relay_and_signed_download() -> None:
    service_client = _FakeBlobServiceClient()
    provider = _provider(service_client)
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

    parsed_upload = urlsplit(upload.url)
    upload_query = parse_qs(parsed_upload.query)
    assert upload.headers == {"content-type": "text/plain"}
    assert parsed_upload.path == f"/api/v1/storage/upload/private/{_private_key('output.txt')}"
    provider.require_valid_upload_signature(
        ref,
        expires=int(upload_query["expires"][0]),
        signature=upload_query["sig"][0],
        content_type="text/plain",
        expected_size_bytes=4,
    )
    with pytest.raises(StorageSignatureError):
        provider.require_valid_upload_signature(
            ref,
            expires=int(upload_query["expires"][0]),
            signature=upload_query["sig"][0],
            content_type="text/plain",
            expected_size_bytes=5,
        )
    assert download.headers == {"content-disposition": 'attachment; filename="output.txt"'}
    assert (
        _fake_generate_blob_sas.calls[0]["content_disposition"]
        == 'attachment; filename="output.txt"'
    )
    assert _fake_generate_blob_sas.calls[0]["permission"].kwargs == {"read": True}
    assert service_client.delegation_key_calls == 1


async def test_azure_workspace_container_is_private_labeled_and_cached() -> None:
    service_client = _FakeBlobServiceClient()
    provider = _provider(service_client)

    await provider.ensure_workspace_bucket(WORKSPACE_ID)
    await provider.ensure_workspace_bucket(WORKSPACE_ID)

    container = service_client.get_container_client(WORKSPACE_CONTAINER)
    assert container.metadata == {"praxis_workspace": str(WORKSPACE_ID)}
    assert container.public_access is None
    assert provider._workspace_container(WORKSPACE_ID) is container


async def test_azure_production_uses_managed_identity_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    def fake_managed_identity_credential(**kwargs):
        captured.update(kwargs)
        return "managed-identity"

    monkeypatch.setattr(
        azure_blob_provider_module,
        "ManagedIdentityCredential",
        fake_managed_identity_credential,
    )
    provider = AzureBlobStorageProvider.__new__(AzureBlobStorageProvider)
    provider.use_managed_identity = True
    provider.managed_identity_client_id = "managed-client-id"

    assert provider._create_credential() == "managed-identity"
    assert captured == {"client_id": "managed-client-id"}


async def test_azure_blob_platform_objects_remain_private_and_sign_in_the_platform_bucket() -> None:
    client = _FakeBlobServiceClient()
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
    assert "/storage/upload/platform_private/platform/" in upload.url
    assert "/platform-private/platform/" in download.url
    assert _fake_generate_blob_sas.calls[-1]["container_name"] == "platform-private"
    assert ref.key in client.get_container_client("platform-private").objects
    assert not client.get_container_client("public").objects
    assert client.existing_containers == {"public", "platform-private"}
    assert await provider.delete_object(ref) is True
    assert await provider.stat_object(ref) is None
    assert await provider.delete_object(ref) is False
