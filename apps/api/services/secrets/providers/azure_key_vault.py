# apps/api/services/secrets/providers/azure_key_vault.py

"""Azure Key Vault implementation of the secrets contract."""

import asyncio
from typing import Any

from core.exceptions.integration import IntegrationAuthError
from core.settings import settings
from services.secrets.domain import SecretReference, validate_secret_name
from services.secrets.utils import cloud_secret_id


class AzureKeyVaultProvider:
    provider_key = "azure_key_vault"

    def __init__(self, *, vault_url: str | None = None, client: Any | None = None) -> None:
        self.vault_url = (vault_url or settings.AZURE_KEY_VAULT_URL or "").strip()
        if not self.vault_url:
            raise IntegrationAuthError(
                "Azure Key Vault URL is not configured",
                provider_key=self.provider_key,
                operation="configure",
            )
        self._client = client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from azure.identity import DefaultAzureCredential
            from azure.keyvault.secrets import SecretClient
        except ImportError as exc:
            raise IntegrationAuthError(
                "Azure Key Vault support requires the azure extra",
                provider_key=self.provider_key,
                operation="configure",
                original_error=exc,
            ) from exc
        credential = DefaultAzureCredential(
            managed_identity_client_id=settings.AZURE_MANAGED_IDENTITY_CLIENT_ID or None
        )
        self._client = SecretClient(vault_url=self.vault_url, credential=credential)
        return self._client

    async def resolve_secret(self, ref: SecretReference) -> str:
        version = None if ref.version == "latest" else ref.version
        try:
            secret = await asyncio.to_thread(
                self._get_client().get_secret,
                cloud_secret_id(ref.name),
                version,
            )
            return secret.value
        except Exception as exc:
            raise IntegrationAuthError(
                "Secret reference could not be resolved",
                provider_key=self.provider_key,
                operation="resolve_secret",
                original_error=exc,
            ) from exc

    async def write_secret(self, name: str, value: str) -> SecretReference:
        validate_secret_name(name)
        try:
            secret = await asyncio.to_thread(
                self._get_client().set_secret,
                cloud_secret_id(name),
                value,
            )
        except Exception as exc:
            raise IntegrationAuthError(
                "Secret could not be written",
                provider_key=self.provider_key,
                operation="write_secret",
                original_error=exc,
            ) from exc
        return SecretReference(
            provider=self.provider_key, name=name, version=secret.properties.version
        )

    async def delete_secret(self, ref: SecretReference) -> bool:
        try:
            poller = await asyncio.to_thread(
                self._get_client().begin_delete_secret,
                cloud_secret_id(ref.name),
            )
            await asyncio.to_thread(poller.wait)
        except Exception as exc:
            raise IntegrationAuthError(
                "Secret could not be deleted",
                provider_key=self.provider_key,
                operation="delete_secret",
                original_error=exc,
            ) from exc
        return True
