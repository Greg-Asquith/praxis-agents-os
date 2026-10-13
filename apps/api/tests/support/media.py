# apps/api/tests/support/media.py

"""Media renderer test helpers."""

import importlib
from collections.abc import Awaitable, Callable
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

from core.settings import settings
from services.storage.domain import StorageBucket, StorageObjectRef, make_storage_object_ref
from tests.support.storage import reset_storage_provider_cache

# The package exports a function with the module's name.
run_media_operation_module = importlib.import_module("services.media.run_media_operation")


def use_fake_renderer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    post: Callable[[dict], Awaitable[dict]],
) -> None:
    """Stages through local storage and answers each renderer request with ``post``."""
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "APP_BASE_URL", "http://testserver")
    monkeypatch.setattr(settings, "MEDIA_RENDERER_URL", "http://renderer.test")
    monkeypatch.setattr(settings, "MEDIA_RENDERER_AUTH", "none")
    monkeypatch.setattr(
        settings, "MEDIA_RENDERER_LOCAL_STORAGE_URL", "http://host.docker.internal:8000"
    )
    reset_storage_provider_cache()
    monkeypatch.setattr(run_media_operation_module, "_post", post)


def staged_ref(url: str) -> StorageObjectRef:
    """Returns the platform staging object a local signed upload URL writes to."""
    key = unquote(urlsplit(url).path.split("/upload/platform_private/", 1)[1])
    return make_storage_object_ref(StorageBucket.PLATFORM_PRIVATE, key)
