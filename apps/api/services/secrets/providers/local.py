# apps/api/services/secrets/providers/local.py

"""Local-only encrypted-file and environment-variable secrets provider."""

import asyncio
import fcntl
import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any

from core.exceptions.integration import (
    IntegrationCredentialUnavailableError,
    IntegrationValidationError,
)
from core.settings import settings
from services.secrets.domain import SecretReference, validate_secret_name
from services.secrets.utils import secret_environment_name
from utils.security import decrypt_data, encrypt_data

API_ROOT = Path(__file__).resolve().parents[3]


class LocalSecretsProvider:
    provider_key = "local"

    def __init__(self, *, store_path: str | Path | None = None) -> None:
        configured_path = Path(store_path or settings.LOCAL_SECRET_STORE_PATH)
        self.store_path = (
            configured_path if configured_path.is_absolute() else API_ROOT / configured_path
        )
        self.lock_path = self.store_path.with_suffix(f"{self.store_path.suffix}.lock")

    async def resolve_secret(self, ref: SecretReference) -> str:
        env_value = os.getenv(secret_environment_name(ref.name))
        if env_value is not None and ref.version in {"env", "latest"}:
            return env_value
        try:
            value = await asyncio.to_thread(self._resolve_from_file, ref)
        except Exception as exc:
            raise self._unavailable_error(original_error=exc) from exc
        if value is None:
            raise self._unavailable_error()
        return value

    async def write_secret(self, name: str, value: str) -> SecretReference:
        validate_secret_name(name)
        if not value:
            raise IntegrationValidationError(
                "Secret value cannot be empty",
                provider_key=self.provider_key,
                operation="write_secret",
            )
        try:
            version = await asyncio.to_thread(self._write_to_file, name, value)
        except Exception as exc:
            raise self._unavailable_error("write_secret", exc) from exc
        return SecretReference(provider=self.provider_key, name=name, version=version)

    async def delete_secret(self, ref: SecretReference) -> bool:
        try:
            return await asyncio.to_thread(self._delete_from_file, ref)
        except Exception as exc:
            raise self._unavailable_error("delete_secret", exc) from exc

    def _unavailable_error(
        self,
        operation: str = "resolve_secret",
        original_error: Exception | None = None,
    ) -> IntegrationCredentialUnavailableError:
        return IntegrationCredentialUnavailableError(
            "Integration credential is temporarily unavailable",
            provider_key=self.provider_key,
            operation=operation,
            original_error=original_error,
        )

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
        encrypted = encrypt_data(serialized).encode("utf-8")
        temporary_fd, temporary_name = tempfile.mkstemp(
            dir=self.store_path.parent,
            prefix=f".{self.store_path.name}.",
            suffix=".tmp",
        )
        try:
            os.fchmod(temporary_fd, 0o600)
            with os.fdopen(temporary_fd, "wb") as temporary_file:
                temporary_file.write(encrypted)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_name, self.store_path)
            self.store_path.chmod(0o600)
            directory_fd = os.open(self.store_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except Exception:
            with suppress(OSError):
                os.close(temporary_fd)
            Path(temporary_name).unlink(missing_ok=True)
            raise

    @contextmanager
    def _file_lock(self, *, exclusive: bool) -> Iterator[None]:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            os.fchmod(lock_fd, 0o600)
            fcntl.flock(lock_fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
            yield
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)

    def _resolve_from_file(self, ref: SecretReference) -> str | None:
        with self._file_lock(exclusive=False):
            versions = self._read_store().get(ref.name, {})
            if ref.version == "latest" and versions:
                return versions[sorted(versions)[-1]]
            return versions.get(ref.version)

    def _write_to_file(self, name: str, value: str) -> str:
        with self._file_lock(exclusive=True):
            store = self._read_store()
            versions: dict[str, Any] = store.setdefault(name, {})
            next_number = max((int(key) for key in versions if key.isdigit()), default=0) + 1
            version = f"{next_number:08d}"
            versions[version] = value
            self._write_store(store)
            return version

    def _delete_from_file(self, ref: SecretReference) -> bool:
        with self._file_lock(exclusive=True):
            store = self._read_store()
            versions = store.get(ref.name)
            if not versions or ref.version not in versions:
                return False
            del versions[ref.version]
            if not versions:
                del store[ref.name]
            self._write_store(store)
            return True
