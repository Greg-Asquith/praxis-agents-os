# apps/api/tests/services/storage/test_azure_blob_provider.py

"""Azure Blob storage provider tests."""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.errors import (
    StorageNotFoundError,
    StoragePreconditionError,
    StorageProviderUnavailableError,
)
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
        workspace_bucket_prefix="praxis-test",
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


async def test_azure_blob_provider_put_get_stat_and_delete_object() -> None:
    service_client = _FakeBlobServiceClient()
    provider = _provider(service_client)
    ref = make_storage_object_ref(StorageBucket.PUBLIC, "users/u_1/avatar/me.png")

    stored = await provider.put_object(
        ref,
        b"png",
        content_type="image/png",
        metadata={"purpose": "avatar"},
    )

    obj = service_client.get_container_client("public").objects[ref.key]
    assert obj["content_settings"].cache_control == "public, max-age=60"
    assert stored.size_bytes == 3
    assert stored.etag == "azure-etag"
    assert stored.content_type == "image/png"
    assert stored.metadata == {"purpose": "avatar"}
    assert stored.public_url == "https://cdn.example/users/u_1/avatar/me.png"
    assert await provider.get_object(ref) == b"png"

    assert await provider.delete_object(ref) is True
    assert await provider.stat_object(ref) is None
    assert await provider.delete_object(ref) is False


async def test_azure_blob_provider_maps_get_not_found_to_storage_error() -> None:
    provider = _provider(_FakeBlobServiceClient())
    ref = make_storage_object_ref(StorageBucket.PRIVATE, _private_key("missing.txt"))

    with pytest.raises(StorageNotFoundError):
        await provider.get_object(ref)

    assert await provider.stat_object(ref) is None


async def test_azure_blob_signed_urls_bind_upload_headers_and_disposition() -> None:
    service_client = _FakeBlobServiceClient()
    provider = _provider(service_client)
    ref = make_storage_object_ref(StorageBucket.PRIVATE, _private_key("output.txt"))

    upload = await provider.create_signed_upload(
        ref,
        content_type="text/plain",
        expires_in=timedelta(minutes=5),
    )
    download = await provider.create_signed_download(
        ref,
        expires_in=timedelta(minutes=5),
        force_download=True,
        filename="output.txt",
    )

    assert upload.headers == {
        "x-ms-blob-type": "BlockBlob",
        "x-ms-blob-content-type": "text/plain",
    }
    assert _fake_generate_blob_sas.calls[0]["container_name"] == WORKSPACE_CONTAINER
    assert _fake_generate_blob_sas.calls[0]["content_type"] == "text/plain"
    assert _fake_generate_blob_sas.calls[0]["permission"].kwargs == {"create": True}
    assert download.headers == {"content-disposition": 'attachment; filename="output.txt"'}
    assert (
        _fake_generate_blob_sas.calls[1]["content_disposition"]
        == 'attachment; filename="output.txt"'
    )
    assert _fake_generate_blob_sas.calls[1]["permission"].kwargs == {"read": True}
    assert service_client.delegation_key_calls == 1


async def test_azure_blob_native_public_url_is_used_without_cdn_base() -> None:
    provider = AzureBlobStorageProvider(
        account_name="storageacct",
        public_container_name="public",
        workspace_bucket_prefix="praxis-test",
        credential=object(),
        service_client=_FakeBlobServiceClient(),
        content_settings_cls=_FakeContentSettings,
        match_conditions_cls=_FakeMatchConditions,
        sas_permissions_cls=_FakePermissions,
        generate_sas_func=_fake_generate_blob_sas,
    )
    ref = make_storage_object_ref(StorageBucket.PUBLIC, "users/u 1/avatar/me.png")

    assert (
        provider.public_url(ref)
        == "https://storageacct.blob.core.windows.net/public/users/u%201/avatar/me.png"
    )


async def test_azure_blob_promotion_is_create_only_and_source_conditional() -> None:
    service_client = _FakeBlobServiceClient()
    provider = _provider(service_client)
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


async def test_azure_blob_provider_missing_required_settings_fail_clearly() -> None:
    with pytest.raises(StorageProviderUnavailableError):
        AzureBlobStorageProvider(
            account_name="",
            public_container_name="public",
            workspace_bucket_prefix="praxis-test",
            credential=object(),
            service_client=_FakeBlobServiceClient(),
            content_settings_cls=_FakeContentSettings,
            match_conditions_cls=_FakeMatchConditions,
            sas_permissions_cls=_FakePermissions,
            generate_sas_func=_fake_generate_blob_sas,
        )


async def test_azure_workspace_container_is_private_labeled_and_cached() -> None:
    service_client = _FakeBlobServiceClient()
    provider = _provider(service_client)

    await provider.ensure_workspace_bucket(WORKSPACE_ID)
    await provider.ensure_workspace_bucket(WORKSPACE_ID)

    container = service_client.get_container_client(WORKSPACE_CONTAINER)
    assert container.metadata == {"praxis_workspace": str(WORKSPACE_ID)}
    assert container.public_access is None
    assert provider._workspace_container(WORKSPACE_ID) is container


async def test_azure_workspace_container_preserves_stored_access_policies() -> None:
    service_client = _FakeBlobServiceClient()
    service_client.existing_containers.add(WORKSPACE_CONTAINER)
    container = service_client.get_container_client(WORKSPACE_CONTAINER)
    container.metadata = {"environment": "staging"}
    container.signed_identifiers = {"operator-policy": object()}
    provider = _provider(service_client)

    await provider.ensure_workspace_bucket(WORKSPACE_ID)

    assert set(container.signed_identifiers) == {"operator-policy"}
    assert container.metadata == {
        "environment": "staging",
        "praxis_workspace": str(WORKSPACE_ID),
    }
    assert container.public_access is None


async def test_azure_provisioning_restores_handle_if_it_is_evicted_while_awaiting() -> None:
    service_client = _FakeBlobServiceClient()
    service_client.existing_containers.add(WORKSPACE_CONTAINER)
    provider = _provider(service_client)
    container = provider._workspace_container(WORKSPACE_ID)
    properties_started = threading.Event()
    release_properties = threading.Event()
    original_get_properties = container.get_container_properties

    def blocking_get_properties() -> dict:
        properties_started.set()
        assert release_properties.wait(timeout=5)
        return original_get_properties()

    container.get_container_properties = blocking_get_properties
    provisioning = asyncio.create_task(provider.ensure_workspace_bucket(WORKSPACE_ID))
    assert await asyncio.to_thread(properties_started.wait, 5)
    for _index in range(256):
        provider._workspace_container(uuid4())
    assert WORKSPACE_ID not in provider._workspace_containers

    release_properties.set()
    await provisioning

    assert provider._workspace_containers[WORKSPACE_ID] is container
    await provider.ensure_workspace_bucket(WORKSPACE_ID)
