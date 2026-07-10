# apps/api/services/secrets/provider.py

"""Secrets-provider protocol."""

from typing import Protocol, runtime_checkable

from services.secrets.domain import SecretReference


@runtime_checkable
class SecretsProvider(Protocol):
    provider_key: str

    async def resolve_secret(self, ref: SecretReference) -> str: ...

    async def write_secret(self, name: str, value: str) -> SecretReference: ...

    async def delete_secret(self, ref: SecretReference) -> bool: ...
