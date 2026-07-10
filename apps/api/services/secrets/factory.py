# apps/api/services/secrets/factory.py

"""Configured secrets-provider factory."""

import threading

from core.exceptions.integration import IntegrationAuthError
from core.settings import settings
from services.secrets.provider import SecretsProvider
from services.secrets.providers.aws_secrets_manager import AwsSecretsManagerProvider
from services.secrets.providers.azure_key_vault import AzureKeyVaultProvider
from services.secrets.providers.gcp_secret_manager import GcpSecretManagerProvider
from services.secrets.providers.local import LocalSecretsProvider

_provider: SecretsProvider | None = None
_provider_key: str | None = None
_lock = threading.Lock()


def get_secrets_provider() -> SecretsProvider:
    global _provider, _provider_key

    provider_key = settings.SECRET_PROVIDER
    if _provider is not None and _provider_key == provider_key:
        return _provider
    with _lock:
        if _provider is not None and _provider_key == provider_key:
            return _provider
        if provider_key == "local":
            resolved: SecretsProvider = LocalSecretsProvider()
        elif provider_key == "gcp_secret_manager":
            resolved = GcpSecretManagerProvider()
        elif provider_key == "azure_key_vault":
            resolved = AzureKeyVaultProvider()
        elif provider_key == "aws_secrets_manager":
            resolved = AwsSecretsManagerProvider()
        else:  # pragma: no cover - Settings rejects unknown literals
            raise IntegrationAuthError(
                "Unknown secrets provider",
                provider_key=provider_key,
                operation="get_secrets_provider",
            )
        _provider = resolved
        _provider_key = provider_key
        return resolved
