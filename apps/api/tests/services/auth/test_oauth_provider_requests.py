"""OAuth provider request diagnostics must not expose credentials or bodies."""

import logging
from urllib.parse import parse_qs

import httpx2
import pytest

from core.auth.oauth_providers import retrying
from core.auth.oauth_providers.google import GoogleOAuthProvider
from core.exceptions.oauth import OAuthAuthenticationError, OAuthNetworkError

SENTINEL = "oauth-secret-sentinel"


def _install_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler,
) -> None:
    original_client = httpx2.AsyncClient
    transport = httpx2.MockTransport(handler)
    monkeypatch.setattr(
        retrying.httpx2,
        "AsyncClient",
        lambda: original_client(transport=transport),
    )


def _provider(monkeypatch: pytest.MonkeyPatch, *, max_retries: int) -> GoogleOAuthProvider:
    provider = GoogleOAuthProvider()
    provider.max_retries = max_retries

    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(retrying.asyncio, "sleep", no_sleep)
    return provider


def _assert_safe_diagnostics(
    caplog: pytest.LogCaptureFixture,
    *,
    expected_attempt: int,
    status_code: int | None = None,
) -> None:
    assert SENTINEL not in caplog.text
    records = [
        record for record in caplog.records if record.name == "core.auth.oauth_providers.retrying"
    ]
    assert records
    assert all(record.exc_info is None for record in records)
    assert any(
        record.provider == "google"
        and record.operation == "test_operation"
        and record.attempt == expected_attempt
        for record in records
    )
    if status_code is not None:
        assert any(record.status_code == status_code for record in records)


async def test_oauth_provider_4xx_diagnostics_redact_url_and_response_body(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(400, text=f"reflected={SENTINEL}", request=request)

    _install_transport(monkeypatch, handler)
    provider = _provider(monkeypatch, max_retries=0)

    with caplog.at_level(logging.INFO), pytest.raises(OAuthAuthenticationError) as exc_info:
        await provider._make_request(
            "POST",
            f"https://provider.example/token?credential={SENTINEL}",
            "test_operation",
        )

    assert SENTINEL not in str(exc_info.value.to_problem_details())
    _assert_safe_diagnostics(caplog, expected_attempt=1, status_code=400)


async def test_oauth_provider_5xx_diagnostics_redact_url_and_response_body(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(503, text=f"provider-body={SENTINEL}", request=request)

    _install_transport(monkeypatch, handler)
    provider = _provider(monkeypatch, max_retries=1)

    with caplog.at_level(logging.INFO), pytest.raises(OAuthNetworkError) as exc_info:
        await provider._make_request(
            "GET",
            f"https://provider.example/token?credential={SENTINEL}",
            "test_operation",
        )

    assert SENTINEL not in str(exc_info.value.to_problem_details())
    _assert_safe_diagnostics(caplog, expected_attempt=2, status_code=503)


async def test_oauth_provider_network_diagnostics_and_problem_detail_are_redacted(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError(f"connection failed: {SENTINEL}", request=request)

    _install_transport(monkeypatch, handler)
    provider = _provider(monkeypatch, max_retries=1)

    with caplog.at_level(logging.INFO), pytest.raises(OAuthNetworkError) as exc_info:
        await provider._make_request(
            "GET",
            f"https://provider.example/token?credential={SENTINEL}",
            "test_operation",
        )

    assert exc_info.value.to_problem_details()["detail"] == "Google OAuth network error"
    _assert_safe_diagnostics(caplog, expected_attempt=2)


async def test_oauth_provider_invalid_token_payload_diagnostic_is_redacted(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = _provider(monkeypatch, max_retries=0)
    response = httpx2.Response(
        200,
        json={"error": SENTINEL},
        request=httpx2.Request("POST", "https://provider.example/token"),
    )

    with caplog.at_level(logging.INFO), pytest.raises(OAuthAuthenticationError):
        provider._parse_token_payload(response, "test_operation")

    assert SENTINEL not in caplog.text
    record = next(
        record
        for record in caplog.records
        if record.getMessage() == "OAuth provider returned an invalid token payload"
    )
    assert record.provider == "google"
    assert record.operation == "test_operation"
    assert record.exc_info is None


async def test_google_oauth_revoke_sends_token_in_form_body(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    captured_request: httpx2.Request | None = None

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal captured_request
        captured_request = request
        return httpx2.Response(200, request=request)

    _install_transport(monkeypatch, handler)
    provider = _provider(monkeypatch, max_retries=0)

    with caplog.at_level(logging.INFO):
        assert await provider.revoke_token(SENTINEL) is True

    assert captured_request is not None
    assert captured_request.url.query == b""
    assert parse_qs(captured_request.content.decode()) == {"token": [SENTINEL]}
    assert SENTINEL not in caplog.text


async def test_google_oauth_revoke_failure_logs_no_exception_or_provider_body(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(400, text=f"reflected={SENTINEL}", request=request)

    _install_transport(monkeypatch, handler)
    provider = _provider(monkeypatch, max_retries=0)

    with caplog.at_level(logging.INFO):
        assert await provider.revoke_token(SENTINEL) is False

    assert SENTINEL not in caplog.text
    relevant_records = [
        record
        for record in caplog.records
        if record.name
        in {
            "core.auth.oauth_providers.google",
            "core.auth.oauth_providers.retrying",
        }
    ]
    assert {record.name for record in relevant_records} == {
        "core.auth.oauth_providers.google",
        "core.auth.oauth_providers.retrying",
    }
    assert all(record.exc_info is None for record in relevant_records)
