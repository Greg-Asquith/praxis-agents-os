"""Security invariants for OAuth login state."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import Response

from core.exceptions.oauth import OAuthAuthenticationError
from services.auth.oauth.complete_oauth_login import complete_oauth_login
from services.auth.oauth.utils import (
    clear_oauth_login_binding_cookie,
    create_oauth_state,
    set_oauth_login_binding_cookie,
    verify_oauth_login_browser_binding,
    verify_oauth_state,
)
from services.auth.schemas import OAuthCallbackRequest


def test_oauth_login_state_is_bound_to_the_initiating_browser() -> None:
    state, expires_at, browser_binding = create_oauth_state(
        provider_name="google",
        redirect_uri="http://localhost:3000/oauth/callback",
        next_path=None,
    )
    state_payload = verify_oauth_state(state)

    verify_oauth_login_browser_binding(
        state_payload,
        request=SimpleNamespace(cookies={"oauth_login_binding": browser_binding}),
        provider_name="google",
    )

    with pytest.raises(
        OAuthAuthenticationError,
        match="OAuth login was not initiated by this browser",
    ):
        verify_oauth_login_browser_binding(
            state_payload,
            request=SimpleNamespace(
                cookies={"oauth_login_binding": "binding-from-another-browser"}
            ),
            provider_name="google",
        )

    response = Response()
    set_oauth_login_binding_cookie(
        response,
        browser_binding=browser_binding,
        expires_at=expires_at,
    )
    cookie_header = response.headers["set-cookie"]
    assert "oauth_login_binding=" in cookie_header
    assert "HttpOnly" in cookie_header
    assert "Path=/api/v1/auth/oauth" in cookie_header
    assert "Domain=" not in cookie_header

    clear_oauth_login_binding_cookie(response)
    assert response.headers.getlist("set-cookie")[-1].startswith('oauth_login_binding="";')


async def test_oauth_login_rejects_transferred_state_before_code_exchange(monkeypatch) -> None:
    state, _, _ = create_oauth_state(
        provider_name="google",
        redirect_uri="http://localhost:3000/oauth/callback",
        next_path=None,
    )
    provider = SimpleNamespace(exchange_code=AsyncMock())
    record_security_event = AsyncMock()

    monkeypatch.setattr(
        "services.auth.oauth.complete_oauth_login.oauth_registry.get_provider",
        lambda _provider_name: provider,
    )
    monkeypatch.setattr(
        "services.auth.oauth.complete_oauth_login.record_auth_security_event",
        record_security_event,
    )

    with pytest.raises(
        OAuthAuthenticationError,
        match="OAuth login was not initiated by this browser",
    ):
        await complete_oauth_login(
            AsyncMock(),
            request=SimpleNamespace(cookies={}),
            response=Response(),
            provider_name="google",
            payload=OAuthCallbackRequest(
                code="attacker-code",
                state=state,
                redirect_uri="http://localhost:3000/oauth/callback",
            ),
        )

    provider.exchange_code.assert_not_awaited()
    record_security_event.assert_awaited_once()
