# apps/api/services/secrets/providers/local.py

"""Local-only encrypted-file and environment-variable secrets provider."""

import asyncio
import json
import os
import threading
from pathlib import Path
from typing import Any

from core.exceptions.integration import IntegrationAuthError
from core.settings import settings
from services.secrets.domain import SecretReference, validate_secret_name
from services.secrets.utils import secret_environment_name
from utils.security import decrypt_data, encrypt_data


class LocalSecretsProvider:
    provider_key = "local"

    def __init__(self, *, storage_root: str | Path | None = None) -> None:
        root = Path(storage_root or settings.LOCAL_STORAGE_ROOT)
        self.store_path = root.parent / "secrets.enc.json"
        self._lock = threading.Lock()

    async def resolve_secret(self, ref: SecretReference) -> str:
        env_value = os.getenv(secret_environment_name(ref.name))
        if env_value is not None and ref.version in {"env", "latest"}:
            return env_value
        value = await asyncio.to_thread(self._resolve_from_file, ref)
        if value is None:
            raise IntegrationAuthError(
                "Secret reference could not be resolved",
                provider_key=self.provider_key,
                operation="resolve_secret",
            )
        return value

    async def write_secret(self, name: str, value: str) -> SecretReference:
        validate_secret_name(name)
        if not value:
            raise IntegrationAuthError(
                "Secret value cannot be empty",
                provider_key=self.provider_key,
                operation="write_secret",
            )
        version = await asyncio.to_thread(self._write_to_file, name, value)
        return SecretReference(provider=self.provider_key, name=name, version=version)

    async def delete_secret(self, ref: SecretReference) -> bool:
        return await asyncio.to_thread(self._delete_from_file, ref)

    def _read_store(self) -> dict[str, dict[str, str]]:
        if not self.store_path.exists():
            return {}
        encrypted = self.store_path.read_text(encoding="utf-8")
        payload = json.loads(decrypt_data(encrypted))
        if not isinstance(payload, dict):
            return {}
        return payload

    def _write_store(self, store: dict[str, dict[str, str]]) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(store, sort_keys=True, separators=(",", ":"))
        self.store_path.write_text(encrypt_data(serialized), encoding="utf-8")
        self.store_path.chmod(0o600)

    def _resolve_from_file(self, ref: SecretReference) -> str | None:
        with self._lock:
            versions = self._read_store().get(ref.name, {})
            if ref.version == "latest" and versions:
                return versions[sorted(versions)[-1]]
            return versions.get(ref.version)

    def _write_to_file(self, name: str, value: str) -> str:
        with self._lock:
            store = self._read_store()
            versions: dict[str, Any] = store.setdefault(name, {})
            next_number = max((int(key) for key in versions if key.isdigit()), default=0) + 1
            version = f"{next_number:08d}"
            versions[version] = value
            self._write_store(store)
            return version

    def _delete_from_file(self, ref: SecretReference) -> bool:
        with self._lock:
            store = self._read_store()
            versions = store.get(ref.name)
            if not versions or ref.version not in versions:
                return False
            del versions[ref.version]
            if not versions:
                del store[ref.name]
            self._write_store(store)
            return True
