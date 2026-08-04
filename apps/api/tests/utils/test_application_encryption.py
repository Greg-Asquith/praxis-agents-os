"""Application encryption key-ring behavior and settings validation."""

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet

from core.settings import Settings, settings
from services.auth.oauth.utils import (
    create_oauth_state,
    verify_oauth_login_browser_binding,
    verify_oauth_state,
)
from utils.security import (
    configure_application_encryption_keys,
    decrypt_data,
    encrypt_data,
    is_encrypted_with_primary,
)

encryption_loader = import_module("services.security.ensure_application_encryption_keys_loaded")


@pytest.fixture(autouse=True)
def _restore_application_encryption_keys():
    original_keys = settings.application_encryption_keys
    yield
    configure_application_encryption_keys(original_keys)


def test_ring_decrypts_old_tokens_and_encrypts_with_primary() -> None:
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()
    configure_application_encryption_keys((old_key,))
    old_token = encrypt_data("secret")

    configure_application_encryption_keys((new_key, old_key))

    assert decrypt_data(old_token) == "secret"
    assert is_encrypted_with_primary(old_token) is False
    new_token = encrypt_data("new-secret")
    assert Fernet(new_key.encode()).decrypt(new_token.encode()) == b"new-secret"
    assert is_encrypted_with_primary(new_token) is True


def test_single_key_ring_setting() -> None:
    key = Fernet.generate_key().decode()
    resolved = Settings(
        _env_file=None,
        ENVIRONMENT="local",
        STORAGE_PROVIDER="local_fs",
        EMAIL_PROVIDER="console",
        SECRET_KEY="x" * 40,
        ENCRYPTION_KEYS=key,
        SECURE_COOKIES=False,
    )

    assert resolved.application_encryption_keys == (key,)


def test_legacy_single_key_setting_is_rejected() -> None:
    with pytest.raises(ValueError, match="ENCRYPTION_KEY"):
        Settings(
            _env_file=None,
            ENVIRONMENT="local",
            STORAGE_PROVIDER="local_fs",
            EMAIL_PROVIDER="console",
            SECRET_KEY="x" * 40,
            ENCRYPTION_KEYS=None,
            ENCRYPTION_KEY=Fernet.generate_key().decode(),
            SECURE_COOKIES=False,
        )


@pytest.mark.parametrize(
    "value",
    ["", "not-a-fernet-key", "[]", '["not-a-fernet-key"]'],
)
def test_settings_reject_malformed_or_empty_key_rings(value: str) -> None:
    with pytest.raises(ValueError, match=r"ENCRYPTION_KEYS|Fernet"):
        Settings(
            _env_file=None,
            ENVIRONMENT="local",
            STORAGE_PROVIDER="local_fs",
            EMAIL_PROVIDER="console",
            SECRET_KEY="x" * 40,
            ENCRYPTION_KEYS=value,
            SECURE_COOKIES=False,
        )


def test_old_key_oauth_cookie_decrypts_during_rotation() -> None:
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()
    configure_application_encryption_keys((old_key,))
    state, _expires_at, browser_binding = create_oauth_state(
        provider_name="google",
        redirect_uri="http://localhost:3000/oauth/callback",
        next_path=None,
    )
    encrypted_binding = encrypt_data(browser_binding)

    configure_application_encryption_keys((new_key, old_key))

    verify_oauth_login_browser_binding(
        verify_oauth_state(state),
        request=SimpleNamespace(cookies={"oauth_login_binding": encrypted_binding}),
        provider_name="google",
    )


async def test_named_secret_source_loads_json_key_ring(monkeypatch) -> None:
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()
    resolve_secret = AsyncMock(return_value=f'["{new_key}", "{old_key}"]')
    monkeypatch.setattr(settings, "ENCRYPTION_KEYS", None)
    monkeypatch.setattr(settings, "ENCRYPTION_KEYS_SECRET_NAME", "application-keys")
    monkeypatch.setattr(settings, "SECRET_PROVIDER", "gcp_secret_manager")
    monkeypatch.setattr(encryption_loader, "resolve_secret", resolve_secret)
    encryption_loader._reset_application_encryption_key_cache()

    try:
        loaded = await encryption_loader.ensure_application_encryption_keys_loaded(AsyncMock())
        assert loaded == (new_key, old_key)
        assert resolve_secret.await_count == 1
    finally:
        encryption_loader._reset_application_encryption_key_cache()
