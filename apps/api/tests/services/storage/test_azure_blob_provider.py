# apps/api/tests/services/storage/test_azure_blob_provider.py

"""Azure Blob storage provider tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.errors import StorageNotFoundError, StorageProviderUnavailableError
from services.storage.providers.azure_blob import AzureBlobStorageProvider

pytestmark = pytest.mark.asyncio


class _AzureNotFoundError(Exception):
    error_code = "BlobNotFound"


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
        self.container.objects[self.key] = {
            "data": data,
            "content_settings": content_settings,
            "metadata": metadata or {},
            "overwrite": overwrite,
        }

    def exists(self) -> bool:
        return self.key in self.container.objects

    def download_blob(self) -> _FakeDownload:
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
    def __init__(self, name: str) -> None:
        self.name = name
        self.objects: dict[str, dict] = {}

    def get_blob_client(self, key: str) -> _FakeBlobClient:
        return _FakeBlobClient(self, key)


class _FakeBlobServiceClient:
    def __init__(self) -> None:
        self.containers: dict[str, _FakeContainer] = {}
        self.delegation_key_calls = 0

    def get_container_client(self, name: str) -> _FakeContainer:
        self.containers.setdefault(name, _FakeContainer(name))
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
        private_container_name="private",
        account_url="https://storageacct.blob.core.windows.net",
        public_assets_base_url="https://cdn.example",
        public_cache_control="public, max-age=60",
        credential=object(),
        service_client=service_client,
        content_settings_cls=_FakeContentSettings,
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
    ref = make_storage_object_ref(StorageBucket.PRIVATE, "runs/run_1/missing.txt")

    with pytest.raises(StorageNotFoundError):
        await provider.get_object(ref)

    assert await provider.stat_object(ref) is None


async def test_azure_blob_signed_urls_bind_upload_headers_and_disposition() -> None:
    service_client = _FakeBlobServiceClient()
    provider = _provider(service_client)
    ref = make_storage_object_ref(StorageBucket.PRIVATE, "runs/run_1/output.txt")

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
    assert _fake_generate_blob_sas.calls[0]["container_name"] == "private"
    assert _fake_generate_blob_sas.calls[0]["content_type"] == "text/plain"
    assert _fake_generate_blob_sas.calls[0]["permission"].kwargs == {"create": True, "write": True}
    assert download.headers == {"content-disposition": 'attachment; filename="output.txt"'}
    assert _fake_generate_blob_sas.calls[1]["content_disposition"] == 'attachment; filename="output.txt"'
    assert _fake_generate_blob_sas.calls[1]["permission"].kwargs == {"read": True}
    assert service_client.delegation_key_calls == 1


async def test_azure_blob_native_public_url_is_used_without_cdn_base() -> None:
    provider = AzureBlobStorageProvider(
        account_name="storageacct",
        public_container_name="public",
        private_container_name="private",
        credential=object(),
        service_client=_FakeBlobServiceClient(),
        content_settings_cls=_FakeContentSettings,
        sas_permissions_cls=_FakePermissions,
        generate_sas_func=_fake_generate_blob_sas,
    )
    ref = make_storage_object_ref(StorageBucket.PUBLIC, "users/u 1/avatar/me.png")

    assert (
        provider.public_url(ref)
        == "https://storageacct.blob.core.windows.net/public/users/u%201/avatar/me.png"
    )


async def test_azure_blob_provider_missing_required_settings_fail_clearly() -> None:
    with pytest.raises(StorageProviderUnavailableError):
        AzureBlobStorageProvider(
            account_name="",
            public_container_name="public",
            private_container_name="private",
            credential=object(),
            service_client=_FakeBlobServiceClient(),
            content_settings_cls=_FakeContentSettings,
            sas_permissions_cls=_FakePermissions,
            generate_sas_func=_fake_generate_blob_sas,
        )
