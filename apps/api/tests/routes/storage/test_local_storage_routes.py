# apps/api/tests/routes/storage/test_local_storage_routes.py

"""Route tests for provider-neutral storage endpoints."""

from collections.abc import Iterator
from datetime import timedelta
from urllib.parse import urlsplit

import pytest
from httpx2 import AsyncClient

from core.settings import settings
from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.factory import get_local_storage_provider
from tests.support.storage import reset_storage_provider_cache

pytestmark = pytest.mark.asyncio


@pytest.fixture
def local_storage_settings(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "APP_BASE_URL", "http://testserver")
    reset_storage_provider_cache()
    try:
        yield
    finally:
        reset_storage_provider_cache()


def _relative_url(absolute_url: str) -> str:
    parsed = urlsplit(absolute_url)
    return f"{parsed.path}?{parsed.query}" if parsed.query else parsed.path


async def test_local_signed_upload_and_download_routes(
    async_client: AsyncClient,
    local_storage_settings: None,
) -> None:
    provider = get_local_storage_provider()
    ref = make_storage_object_ref(StorageBucket.PRIVATE, "runs/run_1/results/output.txt")

    upload = await provider.create_signed_upload(
        ref,
        content_type="text/plain",
        expires_in=timedelta(minutes=5),
    )
    upload_response = await async_client.put(
        _relative_url(upload.url),
        content=b"stored by signed upload",
        headers=upload.headers,
    )
    assert upload_response.status_code == 204

    download = await provider.create_signed_download(
        ref,
        expires_in=timedelta(minutes=5),
        force_download=True,
        filename="output.txt",
    )
    download_response = await async_client.get(_relative_url(download.url))

    assert download_response.status_code == 200
    assert download_response.content == b"stored by signed upload"
    assert download_response.headers["content-type"].startswith("text/plain")
    assert download_response.headers["content-disposition"] == 'attachment; filename="output.txt"'
    assert download_response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in download_response.headers["content-security-policy"]


async def test_local_inline_pdf_is_frameable_only_by_configured_app_origins(
    async_client: AsyncClient,
    local_storage_settings: None,
) -> None:
    provider = get_local_storage_provider()
    ref = make_storage_object_ref(StorageBucket.PRIVATE, "files/report.pdf")
    await provider.put_object(ref, b"%PDF-1.7", content_type="application/pdf")

    preview = await provider.create_signed_download(
        ref,
        expires_in=timedelta(minutes=5),
        force_download=False,
        filename="report.pdf",
    )
    response = await async_client.get(_relative_url(preview.url))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert "x-frame-options" not in response.headers
    assert response.headers["content-security-policy"].startswith("frame-ancestors ")
    assert settings.FRONTEND_URL in response.headers["content-security-policy"]
    assert "frame-ancestors 'none'" not in response.headers["content-security-policy"]


async def test_signed_upload_route_uses_active_provider_selection(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "s3")
    reset_storage_provider_cache()
    try:
        response = await async_client.put(
            "/api/v1/storage/upload/private/runs/run_1/results/output.txt",
            params={
                "expires": "9999999999",
                "sig": "invalid",
                "content_type": "text/plain",
            },
            content=b"stored by signed upload",
            headers={"content-type": "text/plain"},
        )
    finally:
        reset_storage_provider_cache()

    assert response.status_code == 501
    assert response.json()["title"] == "Storage Provider Unavailable"
    assert response.json()["provider_key"] == "s3"


async def test_local_signed_upload_rejects_tampered_content_type(
    async_client: AsyncClient,
    local_storage_settings: None,
) -> None:
    provider = get_local_storage_provider()
    ref = make_storage_object_ref(StorageBucket.PRIVATE, "runs/run_1/results/output.json")

    upload = await provider.create_signed_upload(
        ref,
        content_type="application/json",
        expires_in=timedelta(minutes=5),
    )
    response = await async_client.put(
        _relative_url(upload.url),
        content=b"{}",
        headers={"content-type": "text/plain"},
    )

    assert response.status_code == 400
    assert response.json()["title"] == "Storage Validation Error"


async def test_local_signed_upload_rejects_content_type_parameters(
    async_client: AsyncClient,
    local_storage_settings: None,
) -> None:
    provider = get_local_storage_provider()
    ref = make_storage_object_ref(StorageBucket.PRIVATE, "runs/run_1/results/output.txt")

    upload = await provider.create_signed_upload(
        ref,
        content_type="text/plain",
        expires_in=timedelta(minutes=5),
    )
    response = await async_client.put(
        _relative_url(upload.url),
        content=b"text",
        headers={"content-type": "text/plain; charset=utf-8"},
    )

    assert response.status_code == 400
    assert response.json()["title"] == "Storage Validation Error"


async def test_local_private_download_rejects_tampered_signature_inputs(
    async_client: AsyncClient,
    local_storage_settings: None,
) -> None:
    provider = get_local_storage_provider()
    ref = make_storage_object_ref(StorageBucket.PRIVATE, "runs/run_1/results/output.txt")
    await provider.put_object(ref, b"stored", content_type="text/plain")

    download = await provider.create_signed_download(
        ref,
        expires_in=timedelta(minutes=5),
        force_download=True,
        filename="output.txt",
    )
    response = await async_client.get(
        _relative_url(download.url).replace("filename=output.txt", "filename=other.txt")
    )

    assert response.status_code == 403
    assert response.json()["title"] == "Storage Signature Error"


async def test_local_public_object_route_serves_public_object(
    async_client: AsyncClient,
    local_storage_settings: None,
) -> None:
    provider = get_local_storage_provider()
    ref = make_storage_object_ref(StorageBucket.PUBLIC, "users/u_1/avatar/me.txt")
    stored = await provider.put_object(ref, b"public asset", content_type="text/plain")

    response = await async_client.get(_relative_url(stored.public_url or ""))

    assert response.status_code == 200
    assert response.content == b"public asset"
    assert response.headers["cache-control"] == settings.PUBLIC_ASSETS_CACHE_CONTROL


async def test_local_public_route_does_not_serve_sidecar_metadata(
    async_client: AsyncClient,
    local_storage_settings: None,
) -> None:
    provider = get_local_storage_provider()
    ref = make_storage_object_ref(StorageBucket.PUBLIC, "users/u_1/avatar/me.txt")
    stored = await provider.put_object(
        ref,
        b"public asset",
        content_type="text/plain",
        metadata={"internal": "metadata"},
    )

    response = await async_client.get(f"{_relative_url(stored.public_url or '')}.metadata.json")

    assert response.status_code == 404
    assert response.json()["title"] == "Storage Object Not Found"
