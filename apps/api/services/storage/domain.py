# apps/api/services/storage/domain.py

"""Typed storage contracts shared by providers, routes, and future tools."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from services.storage.errors import StorageValidationError
from services.storage.paths import validate_object_key


class StorageBucket(StrEnum):
    """Logical application storage buckets."""

    PUBLIC = "public"
    PRIVATE = "private"


class StorageObjectRef(BaseModel):
    """Provider-neutral reference to an application-managed object."""

    model_config = ConfigDict(frozen=True)

    bucket: StorageBucket
    key: str = Field(min_length=1, max_length=1024)

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        try:
            return validate_object_key(value)
        except StorageValidationError as exc:
            raise ValueError(str(exc)) from exc

    @property
    def uri(self) -> str:
        return f"storage://{self.bucket.value}/{self.key}"


class StoredObject(BaseModel):
    """Object metadata returned by a storage provider."""

    ref: StorageObjectRef
    size_bytes: int = Field(ge=0)
    etag: str
    content_type: str | None = None
    cache_control: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    public_url: str | None = None
    updated_at: datetime | None = None


class SignedUpload(BaseModel):
    """Provider-generated direct-upload capability."""

    ref: StorageObjectRef
    url: str
    method: Literal["PUT"] = "PUT"
    headers: dict[str, str] = Field(default_factory=dict)
    expires_at: datetime


class SignedDownload(BaseModel):
    """Provider-generated direct-download capability."""

    ref: StorageObjectRef
    url: str
    method: Literal["GET"] = "GET"
    headers: dict[str, str] = Field(default_factory=dict)
    expires_at: datetime


def make_storage_object_ref(bucket: StorageBucket | str, key: str) -> StorageObjectRef:
    """Build a storage ref and raise the storage exception type on bad input."""
    try:
        return StorageObjectRef(bucket=bucket, key=key)
    except ValidationError as exc:
        raise StorageValidationError(
            "Invalid storage object reference",
            operation="object_ref",
            object_key=key,
            original_error=exc,
        ) from exc
