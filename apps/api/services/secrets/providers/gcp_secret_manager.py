# apps/api/services/secrets/providers/gcp_secret_manager.py

"""Google Cloud Secret Manager implementation of the secrets contract."""

import asyncio
from typing import Any

from core.exceptions.integration import IntegrationAuthError
from core.settings import settings
from services.secrets.domain import SecretReference, validate_secret_name
from services.secrets.utils import gcp_secret_id


class GcpSecretManagerProvider:
    provider_key = "gcp_secret_manager"

    def __init__(self, *, project_id: str | None = None, client: Any | None = None) -> None:
        self.project_id = (project_id or settings.GCP_PROJECT_ID or "").strip()
        if not self.project_id:
            raise IntegrationAuthError(
                "GCP project is not configured",
                provider_key=self.provider_key,
                operation="configure",
            )
        self._client = client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from google.cloud import secretmanager
        except ImportError as exc:
            raise IntegrationAuthError(
                "GCP Secret Manager support requires the gcp extra",
                provider_key=self.provider_key,
                operation="configure",
                original_error=exc,
            ) from exc
        self._client = secretmanager.SecretManagerServiceClient()
        return self._client

    async def resolve_secret(self, ref: SecretReference) -> str:
        name = (
            f"projects/{self.project_id}/secrets/{gcp_secret_id(ref.name)}/versions/{ref.version}"
        )
        try:
            response = await asyncio.to_thread(
                self._get_client().access_secret_version,
                request={"name": name},
            )
            return response.payload.data.decode("utf-8")
        except Exception as exc:
            raise IntegrationAuthError(
                "Secret reference could not be resolved",
                provider_key=self.provider_key,
                operation="resolve_secret",
                original_error=exc,
            ) from exc

    async def write_secret(self, name: str, value: str) -> SecretReference:
        validate_secret_name(name)
        secret_id = gcp_secret_id(name)
        client = self._get_client()
        parent = f"projects/{self.project_id}"
        secret_name = f"{parent}/secrets/{secret_id}"
        try:
            try:
                await asyncio.to_thread(client.get_secret, request={"name": secret_name})
            except Exception as exc:
                if type(exc).__name__ != "NotFound":
                    raise
                await asyncio.to_thread(
                    client.create_secret,
                    request={
                        "parent": parent,
                        "secret_id": secret_id,
                        "secret": {"replication": {"automatic": {}}},
                    },
                )
            response = await asyncio.to_thread(
                client.add_secret_version,
                request={"parent": secret_name, "payload": {"data": value.encode("utf-8")}},
            )
        except Exception as exc:
            raise IntegrationAuthError(
                "Secret could not be written",
                provider_key=self.provider_key,
                operation="write_secret",
                original_error=exc,
            ) from exc
        return SecretReference(
            provider=self.provider_key,
            name=name,
            version=str(response.name).rsplit("/", 1)[-1],
        )

    async def delete_secret(self, ref: SecretReference) -> bool:
        name = f"projects/{self.project_id}/secrets/{gcp_secret_id(ref.name)}"
        try:
            await asyncio.to_thread(self._get_client().delete_secret, request={"name": name})
        except Exception as exc:
            raise IntegrationAuthError(
                "Secret could not be deleted",
                provider_key=self.provider_key,
                operation="delete_secret",
                original_error=exc,
            ) from exc
        return True
