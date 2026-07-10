# apps/api/services/secrets/providers/aws_secrets_manager.py

"""AWS Secrets Manager implementation of the secrets contract."""

import asyncio
from typing import Any

from core.exceptions.integration import IntegrationAuthError
from core.settings import settings
from services.secrets.domain import SecretReference, validate_secret_name


class AwsSecretsManagerProvider:
    provider_key = "aws_secrets_manager"

    def __init__(self, *, region: str | None = None, client: Any | None = None) -> None:
        self.region = (region or settings.AWS_REGION or "").strip()
        if not self.region:
            raise IntegrationAuthError(
                "AWS region is not configured",
                provider_key=self.provider_key,
                operation="configure",
            )
        self._client = client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import boto3
        except ImportError as exc:
            raise IntegrationAuthError(
                "AWS Secrets Manager support requires the aws extra",
                provider_key=self.provider_key,
                operation="configure",
                original_error=exc,
            ) from exc
        kwargs: dict[str, Any] = {"region_name": self.region}
        if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY.get_secret_value():
            kwargs.update(
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY.get_secret_value(),
            )
        self._client = boto3.client("secretsmanager", **kwargs)
        return self._client

    async def resolve_secret(self, ref: SecretReference) -> str:
        request: dict[str, str] = {"SecretId": ref.name}
        if ref.version == "latest":
            request["VersionStage"] = "AWSCURRENT"
        else:
            request["VersionId"] = ref.version
        try:
            response = await asyncio.to_thread(self._get_client().get_secret_value, **request)
            return response["SecretString"]
        except Exception as exc:
            raise IntegrationAuthError(
                "Secret reference could not be resolved",
                provider_key=self.provider_key,
                operation="resolve_secret",
                original_error=exc,
            ) from exc

    async def write_secret(self, name: str, value: str) -> SecretReference:
        validate_secret_name(name)
        client = self._get_client()
        try:
            try:
                response = await asyncio.to_thread(
                    client.put_secret_value,
                    SecretId=name,
                    SecretString=value,
                )
            except Exception as exc:
                if type(exc).__name__ != "ResourceNotFoundException":
                    raise
                response = await asyncio.to_thread(
                    client.create_secret,
                    Name=name,
                    SecretString=value,
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
            version=response["VersionId"],
        )

    async def delete_secret(self, ref: SecretReference) -> bool:
        try:
            await asyncio.to_thread(
                self._get_client().delete_secret,
                SecretId=ref.name,
                ForceDeleteWithoutRecovery=True,
            )
        except Exception as exc:
            raise IntegrationAuthError(
                "Secret could not be deleted",
                provider_key=self.provider_key,
                operation="delete_secret",
                original_error=exc,
            ) from exc
        return True
