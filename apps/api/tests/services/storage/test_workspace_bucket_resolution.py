"""Cross-provider workspace bucket isolation contract tests."""

from pathlib import Path
from uuid import UUID

import pytest

from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.errors import StorageValidationError
from services.storage.providers.local import LocalStorageProvider
from tests.services.storage.test_azure_blob_provider import (
    _FakeBlobServiceClient,
    _provider as _azure_provider,
)
from tests.services.storage.test_gcs_provider import (
    _FakeGcsClient,
    _provider as _gcs_provider,
)
from tests.services.storage.test_s3_provider import (
    _FakeS3Client,
    _provider as _s3_provider,
)

pytestmark = pytest.mark.asyncio

WORKSPACE_A = UUID("11111111-1111-4111-8111-111111111111")
WORKSPACE_B = UUID("22222222-2222-4222-8222-222222222222")


def _local_provider(root: Path) -> LocalStorageProvider:
    return LocalStorageProvider(
        root=root,
        app_base_url="http://testserver",
        api_prefix="/api/v1",
        secret_key="x" * 40,
    )


@pytest.mark.parametrize("provider_kind", ["local", "s3", "gcs", "azure_blob"])
async def test_private_object_operations_are_confined_to_the_resolved_workspace_bucket(
    provider_kind: str,
    tmp_path: Path,
) -> None:
    providers = {
        "local": lambda: _local_provider(tmp_path),
        "s3": lambda: _s3_provider(_FakeS3Client()),
        "gcs": lambda: _gcs_provider(_FakeGcsClient()),
        "azure_blob": lambda: _azure_provider(_FakeBlobServiceClient()),
    }
    provider = providers[provider_kind]()
    ref_a = make_storage_object_ref(
        StorageBucket.PRIVATE, f"workspaces/{WORKSPACE_A}/files/shared-name.txt"
    )
    ref_b = make_storage_object_ref(
        StorageBucket.PRIVATE, f"workspaces/{WORKSPACE_B}/files/shared-name.txt"
    )
    promoted_a = make_storage_object_ref(
        StorageBucket.PRIVATE, f"workspaces/{WORKSPACE_A}/files/promoted.txt"
    )

    stored_a = await provider.put_object(ref_a, b"workspace-a", content_type="text/plain")
    await provider.put_object(ref_b, b"workspace-b", content_type="text/plain")
    await provider.ensure_workspace_bucket(WORKSPACE_A)
    await provider.ensure_workspace_bucket(WORKSPACE_A)

    assert await provider.get_object(ref_a) == b"workspace-a"
    assert await provider.get_object(ref_b) == b"workspace-b"
    assert await provider.stat_object(ref_a) is not None
    assert await provider.stat_object(ref_b) is not None

    await provider.promote_object(
        ref_a,
        promoted_a,
        expected_source_etag=stored_a.etag,
    )
    assert await provider.get_object(promoted_a) == b"workspace-a"
    with pytest.raises(StorageValidationError, match="cannot cross workspace buckets"):
        await provider.promote_object(
            ref_a,
            ref_b,
            expected_source_etag=stored_a.etag,
        )

    assert await provider.delete_object(ref_a) is True
    assert await provider.stat_object(ref_a) is None
    assert await provider.get_object(ref_b) == b"workspace-b"


@pytest.mark.parametrize("provider_kind", ["local", "s3", "gcs", "azure_blob"])
async def test_private_non_workspace_keys_fail_closed(
    provider_kind: str,
    tmp_path: Path,
) -> None:
    providers = {
        "local": lambda: _local_provider(tmp_path),
        "s3": lambda: _s3_provider(_FakeS3Client()),
        "gcs": lambda: _gcs_provider(_FakeGcsClient()),
        "azure_blob": lambda: _azure_provider(_FakeBlobServiceClient()),
    }
    provider = providers[provider_kind]()
    ref = make_storage_object_ref(StorageBucket.PRIVATE, "uploads/legacy.txt")

    with pytest.raises(StorageValidationError, match="must use the workspaces"):
        await provider.put_object(ref, b"blocked")
