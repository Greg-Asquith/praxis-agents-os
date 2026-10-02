# apps/api/integrations/meta_ads/client.py

"""Bounded Meta Graph reads and changes over the shared integration HTTP transport."""

import hashlib
import hmac
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
    IntegrationReportTooLargeError,
    IntegrationValidationError,
)
from services.integrations.http import (
    IntegrationRequestPolicy,
    consume_stream_with_retries,
    resolve_before_dispatch,
)
from services.integrations.report_results import report_result_max_bytes

from .throttle import record_usage, throttle_message
from .utils import suppress_request_logging

META_GRAPH_API_VERSION = "v26.0"
AccessTokenFn = Callable[[], Awaitable[str]]


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
        max_response_bytes: int | None = None,
        usage_account_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            path,
            operation=operation,
            policy=policy,
            params=params,
            max_response_bytes=max_response_bytes,
            usage_account_id=usage_account_id,
        )

    async def graph_post(
        self,
        path: str,
        *,
        data: dict[str, Any],
        operation: str,
        policy: IntegrationRequestPolicy,
        max_response_bytes: int | None = None,
        usage_account_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            path,
            operation=operation,
            policy=policy,
            data=data,
            max_response_bytes=max_response_bytes,
            usage_account_id=usage_account_id,
        )

    async def graph_post_form(
        self,
        path: str,
        *,
        data: dict[str, Any],
        files: dict[str, tuple[str, bytes, str]],
        operation: str,
        max_response_bytes: int | None = None,
        usage_account_id: str | None = None,
    ) -> dict[str, Any]:
        """Sends one multipart change, such as a media upload, without retrying."""
        return await self._request(
            "POST",
            path,
            operation=operation,
            policy=IntegrationRequestPolicy.MUTATION,
            data=data,
            files=files,
            max_response_bytes=max_response_bytes,
            usage_account_id=usage_account_id,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        policy: IntegrationRequestPolicy,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        max_response_bytes: int | None = None,
        usage_account_id: str | None = None,
    ) -> dict[str, Any]:
        url = _graph_url(path)
        token = await resolve_before_dispatch(self._access_token)
        secret = self._app_secret.get_secret_value() if self._app_secret else ""
        proof = (
            hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest() if secret else ""
        )
        query = _request_values(params)
        if proof:
            query["appsecret_proof"] = proof
        body_data = _request_values(data) if data is not None else None
        account_match = re.match(r"/?act_([0-9]+)(?:/|$)", path)
        account_id = account_match[1] if account_match else (usage_account_id or "")
        last_detail = ""

        def map_error(response: httpx2.Response) -> IntegrationError | None:
            nonlocal last_detail
            record_usage(account_id, response.headers)
            last_detail = _meta_error_detail(response)
            return _meta_response_error(response, operation=operation, has_secret=bool(secret))

        async def consume(response: httpx2.Response) -> httpx2.Response:
            record_usage(account_id, response.headers)
            maximum = (
                max_response_bytes if max_response_bytes is not None else report_result_max_bytes()
            )
            return await _consume_response(response, maximum, operation)

        try:
            with suppress_request_logging():
                response = await consume_stream_with_retries(
                    method,
                    url,
                    operation=operation,
                    provider_key="meta_ads",
                    policy=policy,
                    client=self._client,
                    headers={"Authorization": f"Bearer {token}"},
                    params=query,
                    data=body_data,
                    **({"files": files} if files is not None else {}),
                    consume=consume,
                    include_original_error=False,
                    response_error_mapper=map_error,
                    follow_redirects=False,
                )
        except IntegrationError as exc:
            _sanitise_error(exc, (token, proof, secret), last_detail)
            raise exc from None
        try:
            return _response_payload(response, operation)
        except IntegrationValidationError as exc:
            # Meta accepted the request, so an unreadable reply cannot prove a change failed.
            if policy is IntegrationRequestPolicy.MUTATION:
                exc.failure_disposition = IntegrationFailureDisposition.AMBIGUOUS
            raise

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
            cursor = next_cursor(next_url, path, operation)
            if cursor in seen:
                return rows, True
            seen.add(cursor)
            query["after"] = cursor
        return rows, True


def _request_values(values: dict[str, Any] | None) -> dict[str, Any]:
    result = dict(values or {})
    result.pop("access_token", None)
    result.pop("appsecret_proof", None)
    return result


async def _consume_response(
    response: httpx2.Response, maximum: int, operation: str
) -> httpx2.Response:
    body = bytearray()
    async for chunk in response.aiter_bytes():
        if len(body) + len(chunk) > maximum:
            raise IntegrationReportTooLargeError(
                "The report exceeds the file size limit. Request fewer fields or a shorter date range.",
                provider_key="meta_ads",
                operation=operation,
            )
        body.extend(chunk)
    return httpx2.Response(response.status_code, content=bytes(body))


def _sanitise_error(
    error: IntegrationError, sensitive_values: tuple[str, ...], detail: str
) -> None:
    error.original_error = None
    message = error.user_message
    append_detail = bool(detail) and (
        isinstance(error, IntegrationConnectionError)
        or error.error_code == "meta_ads_invalid_insights"
    )
    # Redact both components before reserving room for the support reference.
    for sensitive in sensitive_values:
        if sensitive:
            message = message.replace(sensitive, "[redacted]")
            detail = detail.replace(sensitive, "[redacted]")
    detail = detail[:500]
    error.user_message = (
        f"{message[: 999 - len(detail)]} {detail}" if append_detail else message[:1000]
    )
    error.args = (error.user_message,)


def _response_payload(response: httpx2.Response, operation: str) -> dict[str, Any]:
    if response.is_redirect:
        raise _invalid_response("Meta Ads returned an unexpected redirect.", operation)
    try:
        payload = response.json()
    except (ValueError, RecursionError):
        raise _invalid_response("Meta Ads returned an invalid response.", operation) from None
    if not isinstance(payload, dict) or "error" in payload:
        raise _invalid_response("Meta Ads returned an invalid response.", operation)
    return payload


def _graph_url(path: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_]+(?:/[A-Za-z0-9_]+)*", path.lstrip("/")):
        raise _invalid_response("Meta Ads request path is invalid.", "validate_path")
    return f"https://graph.facebook.com/{META_GRAPH_API_VERSION}/{path.lstrip('/')}"


def next_cursor(value: Any, path: str, operation: str) -> str:
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
    except (ValueError, RecursionError):
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
    if (
        response.status_code == 429
        or code in (4, 17, 32, 613)
        or (isinstance(code, int) and 80000 <= code <= 80014)
    ):
        return IntegrationRateLimitError(
            f"{throttle_message(response.headers)} {detail}", **context
        )
    if code == 100 and error.get("error_subcode") == 1487534:
        return IntegrationValidationError(
            "Meta Ads requires a background report for this query.",
            error_code="meta_ads_insights_too_large",
            **context,
        )
    if code == 100 and operation == "run_insights":
        return IntegrationValidationError(
            str(error.get("message", detail)),
            error_code="meta_ads_invalid_insights",
            **context,
        )
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
