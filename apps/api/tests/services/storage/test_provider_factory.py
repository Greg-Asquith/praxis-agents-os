# apps/api/tests/services/storage/test_provider_factory.py

"""Storage provider factory tests."""

from core.settings import settings
from services.storage import factory as storage_factory
from tests.support.storage import reset_storage_provider_cache


class _DummyProvider:
    provider_key = "dummy"

    @classmethod
    def from_settings(cls, _settings):
        return cls()


class _DummyGcsProvider(_DummyProvider):
    provider_key = "gcs"


class _DummyS3Provider(_DummyProvider):
    provider_key = "s3"


class _DummyAzureProvider(_DummyProvider):
    provider_key = "azure_blob"


def test_factory_returns_concrete_cloud_providers(monkeypatch) -> None:
    cases = (
        ("gcs", "GcsStorageProvider", _DummyGcsProvider),
        ("s3", "S3StorageProvider", _DummyS3Provider),
        ("azure_blob", "AzureBlobStorageProvider", _DummyAzureProvider),
    )

    try:
        for provider_key, factory_name, provider_cls in cases:
            monkeypatch.setattr(storage_factory, factory_name, provider_cls)
            monkeypatch.setattr(settings, "STORAGE_PROVIDER", provider_key)
            reset_storage_provider_cache()

            provider = storage_factory.get_storage_provider()

            assert isinstance(provider, provider_cls)
            assert provider.provider_key == provider_key
    finally:
        reset_storage_provider_cache()
