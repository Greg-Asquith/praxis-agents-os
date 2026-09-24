# apps/api/integrations/meta_ads/client.py

"""Bounded Meta Graph reads over the shared integration HTTP transport."""

import hashlib
import hmac
import json
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2
from pydantic import SecretStr

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationConnectionError,
    IntegrationError,
    IntegrationFailureDisposition,
    IntegrationPermissionError,
    IntegrationRateLimitError,
    IntegrationValidationError,
)
from services.integrations.http import (
    IntegrationRequestPolicy,
    request_with_retries,
    resolve_before_dispatch,
)

from .utils import suppress_request_logging

META_GRAPH_API_VERSION = "v26.0"
AccessTokenFn = Callable[[], Awaitable[str]]
logger = logging.getLogger(__name__)


class MetaAdsClient:
    def __init__(
        self,
        access_token: AccessTokenFn,
        *,
        app_secret: SecretStr | None = None,
        client: httpx2.AsyncClient | None = None,
    ) -> None:
        self._access_token = access_token
        self._app_secret = app_secret
        self._client = client

    async def graph_get(
        self,
        path: str,
        *,
        operation: str,
        policy: IntegrationRequestPolicy,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = _graph_url(path)
        token = await resolve_before_dispatch(self._access_token)
        query = dict(params or {})
        query.pop("access_token", None)
        query.pop("appsecret_proof", None)
        secret = self._app_secret.get_secret_value() if self._app_secret else ""
        proof = (
            hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest() if secret else ""
        )
        if proof:
            query["appsecret_proof"] = proof
        last_detail = ""

        def map_error(response: httpx2.Response) -> IntegrationError | None:
            nonlocal last_detail
            last_detail = _meta_error_detail(response)
            return _meta_response_error(response, operation=operation, has_secret=bool(secret))

        try:
            with suppress_request_logging():
                response = await request_with_retries(
                    "GET",
                    url,
                    operation=operation,
                    provider_key="meta_ads",
                    policy=policy,
                    client=self._client,
                    headers={"Authorization": f"Bearer {token}"},
                    params=query,
                    response_error_mapper=map_error,
                    follow_redirects=False,
                )
        except IntegrationError as exc:
            exc.original_error = None
            if last_detail and isinstance(
                exc, (IntegrationConnectionError, IntegrationRateLimitError)
            ):
                exc.user_message = f"{exc.user_message} {last_detail}"
            for sensitive in (token, proof, secret):
                if sensitive:
                    exc.user_message = exc.user_message.replace(sensitive, "[redacted]")
            exc.args = (exc.user_message,)
            raise exc from None
        if response.is_redirect:
            raise _invalid_response("Meta Ads returned an unexpected redirect.", operation)
        try:
            payload = response.json()
        except ValueError:
            raise _invalid_response("Meta Ads returned an invalid response.", operation) from None
        if not isinstance(payload, dict) or "error" in payload:
            raise _invalid_response("Meta Ads returned an invalid response.", operation)
        _log_usage(response)
        return payload

    async def graph_get_paged(
        self,
        path: str,
        *,
        operation: str,
        policy: IntegrationRequestPolicy,
        params: dict[str, Any] | None = None,
        max_pages: int = 20,
    ) -> tuple[list[dict[str, Any]], bool]:
        if max_pages < 1:
            raise _invalid_response("Meta Ads page limit must be positive.", operation)
        query = dict(params or {})
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for _ in range(max_pages):
            payload = await self.graph_get(path, operation=operation, policy=policy, params=query)
            data = payload.get("data")
            if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                raise _invalid_response("Meta Ads returned an invalid list.", operation)
            rows.extend(data)
            paging = payload.get("paging", {})
            if not isinstance(paging, dict):
                raise _invalid_response("Meta Ads returned invalid pagination.", operation)
            next_url = paging.get("next")
            if not next_url:
                return rows, False
            cursor = _next_cursor(next_url, path, operation)
            if cursor in seen:
                return rows, True
            seen.add(cursor)
            query["after"] = cursor
        return rows, True


def _graph_url(path: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_]+(?:/[A-Za-z0-9_]+)*", path.lstrip("/")):
        raise _invalid_response("Meta Ads request path is invalid.", "validate_path")
    return f"https://graph.facebook.com/{META_GRAPH_API_VERSION}/{path.lstrip('/')}"


def _next_cursor(value: Any, path: str, operation: str) -> str:
    try:
        parsed = urlsplit(value) if isinstance(value, str) else None
        expected = urlsplit(_graph_url(path))
        if (
            parsed is None
            or parsed.scheme != "https"
            or parsed.hostname != "graph.facebook.com"
            or parsed.port not in (None, 443)
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or not _same_edge(parsed.path, expected.path)
        ):
            raise ValueError
        values = parse_qs(parsed.query).get("after", [])
        if len(values) != 1 or not values[0]:
            raise ValueError
        return values[0]
    except ValueError:
        raise _invalid_response("Meta Ads returned an invalid pagination URL.", operation) from None


def _same_edge(actual: str, expected: str) -> bool:
    if actual == expected:
        return True
    prefix = f"/{META_GRAPH_API_VERSION}/me/"
    if not expected.startswith(prefix):
        return False
    edge = re.escape(expected.removeprefix(prefix))
    return bool(re.fullmatch(rf"/{re.escape(META_GRAPH_API_VERSION)}/[0-9]+/{edge}", actual))


def _meta_error_payload(response: httpx2.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    error = payload.get("error") if isinstance(payload, dict) else None
    return error if isinstance(error, dict) else {}


def _meta_error_detail(response: httpx2.Response) -> str:
    trace = _meta_error_payload(response).get("fbtrace_id")
    if isinstance(trace, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", trace):
        return f"Meta Ads rejected the request. Reference: {trace}"[:1000]
    return "Meta Ads rejected the request."


def _meta_response_error(
    response: httpx2.Response,
    *,
    operation: str,
    has_secret: bool,
) -> IntegrationError | None:
    error = _meta_error_payload(response)
    code = error.get("code")
    message = str(error.get("message", "")).lower()
    context = {
        "provider_key": "meta_ads",
        "operation": operation,
        "failure_disposition": IntegrationFailureDisposition.REJECTED,
    }
    detail = _meta_error_detail(response)
    if "appsecret_proof" in message:
        guidance = (
            "This token was generated for a different Meta app than the one this workspace "
            "is set up for. Generate it for the agency's Meta app."
            if has_secret
            else "This token's Meta app requires an app secret. Ask your Praxis administrator "
            "to add the app secret."
        )
        return IntegrationValidationError(f"{guidance} {detail}", **context)
    if code == 190:
        return IntegrationAuthError(
            f"The Meta Ads access token expired or was revoked. Replace it to reconnect. {detail}",
            **context,
        )
    if code == 10 or (isinstance(code, int) and 200 <= code <= 299):
        return IntegrationPermissionError(
            f"Check the system user's asset assignments and token permissions. {detail}", **context
        )
    if code in (4, 17, 32, 613) or (isinstance(code, int) and 80000 <= code <= 80014):
        response.status_code = 429
        return None
    if code in (1, 2) or error.get("is_transient") is True:
        response.status_code = 503
        return None
    if error:
        return IntegrationValidationError(detail, **context)
    return None


def _invalid_response(message: str, operation: str) -> IntegrationValidationError:
    return IntegrationValidationError(message, provider_key="meta_ads", operation=operation)


def normalize_ad_account_id(value: str) -> str:
    result = value.removeprefix("act_") if isinstance(value, str) else ""
    if not re.fullmatch(r"[0-9]+", result):
        raise _invalid_response("Meta Ads account ID must contain digits only.", "account_id")
    return result


def ad_account_path(account_id: str) -> str:
    if not isinstance(account_id, str) or not re.fullmatch(r"[0-9]+", account_id):
        raise _invalid_response("Meta Ads account ID must contain digits only.", "account_id")
    return f"act_{account_id}"


def _log_usage(response: httpx2.Response) -> None:
    value = response.headers.get("X-Business-Use-Case-Usage", "")
    if not value or len(value) > 16_384:
        return
    try:
        usage = json.loads(value)
    except ValueError:
        return
    if not isinstance(usage, dict):
        return
    for entries in usage.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict):
                safe = {
                    key: entry[key]
                    for key in ("call_count", "total_cputime", "total_time")
                    if type(entry.get(key)) in (int, float)
                }
                logger.debug("Meta Ads usage: %s", safe)
