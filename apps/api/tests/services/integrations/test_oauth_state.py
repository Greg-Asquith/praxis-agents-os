"""Deterministic tests for signed integration OAuth state and PKCE crypto."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from cryptography.fernet import Fernet, InvalidToken

from core.exceptions.integration import IntegrationAuthError
from core.settings import settings
from services.integrations.oauth.utils import (
    code_challenge,
    create_integration_oauth_state,
    decrypt_code_verifier,
    encrypt_code_verifier,
    generate_code_verifier,
    safe_next_path,
    verify_integration_oauth_state,
)
from services.integrations.utils import (
    _reset_credential_key_cache,
    decrypt_credential_token,
    ensure_credential_keys_loaded,
)


def test_state_round_trip_preserves_bound_claims() -> None:
    connection_id = uuid4()
    workspace_id = uuid4()
    user_id = uuid4()
    state, claims = create_integration_oauth_state(
        connection_id=connection_id,
        provider_key="gmail",
        owner_scope="user",
        workspace_id=workspace_id,
        user_id=user_id,
        next_path="/integrations?tab=gmail",
    )
    verified = verify_integration_oauth_state(state)
    assert verified["connection_id"] == str(connection_id)
    assert verified["workspace_id"] == str(workspace_id)
    assert verified["user_id"] == str(user_id)
    assert verified["jti"] == claims["jti"]
    assert verified["next_path"] == "/integrations?tab=gmail"


def test_tampered_state_is_rejected() -> None:
    state, _ = create_integration_oauth_state(
        connection_id=uuid4(),
        provider_key="gmail",
        owner_scope="user",
        workspace_id=uuid4(),
        user_id=uuid4(),
        next_path=None,
    )
    replacement = "A" if state[-1] != "A" else "B"
    with pytest.raises(IntegrationAuthError):
        verify_integration_oauth_state(f"{state[:-1]}{replacement}")


def test_expired_and_login_flow_states_are_rejected() -> None:
    past = int((datetime.now(UTC) - timedelta(minutes=10)).timestamp())
    expired = jwt.encode(
        {
            "type": "integration_oauth_state",
            "connection_id": str(uuid4()),
            "provider_key": "gmail",
            "owner_scope": "user",
            "workspace_id": str(uuid4()),
            "user_id": str(uuid4()),
            "jti": "expired-state",
            "iat": past - 600,
            "exp": past,
        },
        settings.SECRET_KEY.get_secret_value(),
        algorithm="HS256",
    )
    login_state = jwt.encode(
        {
            "type": "oauth_state",
            "provider": "google",
            "jti": "login-state",
            "iat": int(datetime.now(UTC).timestamp()),
            "exp": int((datetime.now(UTC) + timedelta(minutes=10)).timestamp()),
        },
        settings.SECRET_KEY.get_secret_value(),
        algorithm="HS256",
    )
    with pytest.raises(IntegrationAuthError):
        verify_integration_oauth_state(expired)
    with pytest.raises(IntegrationAuthError):
        verify_integration_oauth_state(login_state)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("/integrations", "/integrations"),
        ("https://attacker.example/path", None),
        ("//attacker.example/path", None),
        ("integrations", None),
        (None, None),
    ],
)
def test_safe_next_path(value: str | None, expected: str | None) -> None:
    assert safe_next_path(value) == expected


async def test_pkce_verifier_uses_separate_key_purpose(monkeypatch) -> None:
    monkeypatch.setattr(settings, "CREDENTIAL_MASTER_KEYS", Fernet.generate_key().decode())
    _reset_credential_key_cache()
    db = object()
    await ensure_credential_keys_loaded(db)  # type: ignore[arg-type]
    verifier = generate_code_verifier()
    ciphertext = await encrypt_code_verifier(db, verifier)  # type: ignore[arg-type]
    assert 43 <= len(verifier) <= 128
    assert await decrypt_code_verifier(db, ciphertext) == verifier  # type: ignore[arg-type]
    assert "=" not in code_challenge(verifier)
    with pytest.raises(InvalidToken):
        decrypt_credential_token(ciphertext)
    _reset_credential_key_cache()
