"""Google Indexing API operation and tool coverage."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry

from core.exceptions.integration import (
    IntegrationFailureDisposition,
    IntegrationPermissionError,
    IntegrationRateLimitError,
    IntegrationTimeoutError,
    IntegrationValidationError,
)
from integrations.google_search_console.operations.get_url_notification_metadata import (
    get_url_notification_metadata,
)
from integrations.google_search_console.operations.publish_url_notification import (
    publish_url_notification,
)
from integrations.google_search_console.tools.request_indexing import (
    DEFINITION,
    _approval_display_args,
    google_search_console_request_indexing,
)
from integrations.google_search_console.tools.schemas import (
    GoogleSearchConsoleIndexingNotification,
)
from services.audit_events import AuditStatus
from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry
from services.integrations.http import IntegrationRequestPolicy

NOTIFICATION_METADATA = json.loads(
    (Path(__file__).with_name("fixtures") / "notification_metadata.json").read_text(
        encoding="utf-8"
    )
)


class _Client:
    def __init__(self, response: Any = None) -> None:
        self.response = response
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def indexing_post(self, path: str, **kwargs: Any) -> Any:
        self.calls.append(("POST", path, kwargs))
        return self.response

    async def indexing_get(self, path: str, **kwargs: Any) -> Any:
        self.calls.append(("GET", path, kwargs))
        return self.response


def _entry(*, permission_level: str = "siteOwner") -> ResolvedContextEntry:
    return ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="google_search_console",
        resource_type="google_search_console_site",
        external_id="https://example.com/",
        display_name="example.com",
        connection_id=uuid4(),
        connection_label="Search Console",
        connection_status="active",
        write_allowed=True,
        permissions_metadata={"permission_level": permission_level},
    )


def _ctx(entry: ResolvedContextEntry) -> SimpleNamespace:
    return SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(entry,)),
            db=object(),
            user=SimpleNamespace(id=uuid4()),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4(), name="Search Agent"),
            run=SimpleNamespace(id=uuid4(), user_id=uuid4()),
        ),
        tool_name="google_search_console_request_indexing",
        tool_call_id="call-request-indexing",
    )


def _notification(
    *,
    url: str = "https://example.com/jobs/one",
    notification_type: str = "URL_UPDATED",
) -> GoogleSearchConsoleIndexingNotification:
    return GoogleSearchConsoleIndexingNotification(
        url=url,
        notification_type=notification_type,
        page_type="job_posting",
    )


async def test_indexing_operations_declare_mutation_and_read_policies() -> None:
    publish_client = _Client({"urlNotificationMetadata": {}})
    await publish_url_notification(
        publish_client,
        url="https://example.com/jobs/one",
        notification_type="URL_UPDATED",
    )
    assert publish_client.calls == [
        (
            "POST",
            "urlNotifications:publish",
            {
                "operation": "publish_url_notification",
                "policy": IntegrationRequestPolicy.MUTATION,
                "json": {
                    "url": "https://example.com/jobs/one",
                    "type": "URL_UPDATED",
                },
            },
        )
    ]

    metadata_client = _Client(NOTIFICATION_METADATA)
    result = await get_url_notification_metadata(
        metadata_client,
        url="https://example.com/jobs/one",
        notification_type="URL_UPDATED",
    )
    assert metadata_client.calls[0] == (
        "GET",
        "urlNotifications/metadata",
        {
            "operation": "get_url_notification_metadata",
            "policy": IntegrationRequestPolicy.READ,
            "params": {"url": "https://example.com/jobs/one"},
        },
    )
    assert result == {
        "url": "https://example.com/jobs/one",
        "notification_type": "URL_UPDATED",
        "notify_time": "2026-09-03T12:00:00Z",
    }


async def test_publish_treats_an_invalid_success_payload_as_ambiguous() -> None:
    with pytest.raises(IntegrationValidationError) as exc_info:
        await publish_url_notification(
            _Client([]),
            url="https://example.com/jobs/one",
            notification_type="URL_UPDATED",
        )

    assert exc_info.value.failure_disposition is IntegrationFailureDisposition.AMBIGUOUS


async def test_request_indexing_records_pending_and_metadata_evidence(monkeypatch) -> None:
    audit = AsyncMock(return_value=uuid4())
    publish = AsyncMock()
    metadata = AsyncMock(
        return_value={
            "url": "https://example.com/jobs/one",
            "notification_type": "URL_UPDATED",
            "notify_time": "2026-09-03T12:00:00Z",
        }
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )
    monkeypatch.setattr(
        "integrations.google_search_console.tools.request_indexing.google_search_console_client",
        AsyncMock(return_value="client"),
    )
    monkeypatch.setattr(
        "integrations.google_search_console.tools.request_indexing.publish_url_notification",
        publish,
    )
    monkeypatch.setattr(
        "integrations.google_search_console.tools.request_indexing.get_url_notification_metadata",
        metadata,
    )

    result = await google_search_console_request_indexing(
        _ctx(_entry()),
        notifications=[_notification()],
    )

    publish.assert_awaited_once_with(
        "client",
        url="https://example.com/jobs/one",
        notification_type="URL_UPDATED",
    )
    model_data = result.return_value["results"][0]["data"]
    assert model_data == {
        "notifications": [
            {
                "url": "https://example.com/jobs/one",
                "notification_type": "URL_UPDATED",
                "page_type": "job_posting",
                "outcome": "notified",
                "notify_time": "2026-09-03T12:00:00Z",
                "error_code": None,
            }
        ],
        "notified_count": 1,
        "failed_count": 0,
    }
    pending = audit.await_args_list[0].kwargs["operation_detail"]
    terminal = audit.await_args_list[1].kwargs["operation_detail"]
    assert pending.intent_groups[0].key == "url:notify"
    assert pending.intent_groups[0].items[0].fields == {
        "url": "https://example.com/jobs/one",
        "notification_type": "URL_UPDATED",
        "page_type": "job_posting",
    }
    assert terminal.intent_counts.applied == 1
    assert terminal.outcome_groups[0].outcomes[0].fields == {"notify_time": "2026-09-03T12:00:00Z"}
    assert audit.await_args_list[1].kwargs["status"] is AuditStatus.SUCCESS


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (
            IntegrationPermissionError(
                "ACCESS_TOKEN_SCOPE_INSUFFICIENT",
                failure_disposition=IntegrationFailureDisposition.REJECTED,
            ),
            "scope_missing",
        ),
        (
            IntegrationPermissionError(
                "SERVICE_DISABLED",
                failure_disposition=IntegrationFailureDisposition.REJECTED,
            ),
            "api_not_enabled",
        ),
        (
            IntegrationPermissionError(
                "Google Search Console rejected publish_url_notification: "
                "Permission denied. Failed to verify the URL ownership.",
                failure_disposition=IntegrationFailureDisposition.REJECTED,
            ),
            "not_owner",
        ),
        (
            IntegrationRateLimitError(
                "quota",
                failure_disposition=IntegrationFailureDisposition.AMBIGUOUS,
            ),
            "quota_exhausted",
        ),
        (
            IntegrationTimeoutError(
                "timeout",
                failure_disposition=IntegrationFailureDisposition.AMBIGUOUS,
            ),
            "unverified",
        ),
    ],
)
async def test_request_indexing_maps_provider_failures(monkeypatch, error, expected_code) -> None:
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        AsyncMock(return_value=uuid4()),
    )
    monkeypatch.setattr(
        "integrations.google_search_console.tools.request_indexing.google_search_console_client",
        AsyncMock(return_value="client"),
    )
    monkeypatch.setattr(
        "integrations.google_search_console.tools.request_indexing.publish_url_notification",
        AsyncMock(side_effect=error),
    )

    result = await google_search_console_request_indexing(
        _ctx(_entry()),
        notifications=[_notification()],
    )

    row = result.metadata["public_result"]["results"][0]["data"]["notifications"][0]
    assert row["error_code"] == expected_code
    assert row["outcome"] == ("unverified" if expected_code == "unverified" else "failed")


async def test_request_indexing_keeps_confirmed_publish_when_metadata_read_fails(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        AsyncMock(return_value=uuid4()),
    )
    monkeypatch.setattr(
        "integrations.google_search_console.tools.request_indexing.google_search_console_client",
        AsyncMock(return_value="client"),
    )
    monkeypatch.setattr(
        "integrations.google_search_console.tools.request_indexing.publish_url_notification",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "integrations.google_search_console.tools.request_indexing.get_url_notification_metadata",
        AsyncMock(
            side_effect=IntegrationTimeoutError(
                "metadata timeout",
                failure_disposition=IntegrationFailureDisposition.REJECTED,
            )
        ),
    )

    result = await google_search_console_request_indexing(
        _ctx(_entry()),
        notifications=[_notification()],
    )

    row = result.metadata["public_result"]["results"][0]["data"]["notifications"][0]
    assert row["outcome"] == "notified"
    assert row["error_code"] == "status_unavailable"


async def test_indexing_requires_owner_permission_before_approval() -> None:
    with pytest.raises(ModelRetry, match="Owner permission"):
        await _approval_display_args(
            _ctx(_entry(permission_level="siteFullUser")).deps,
            {"notifications": [_notification().model_dump()]},
        )


def test_indexing_definition_is_approval_only_and_setting_gated(monkeypatch) -> None:
    assert DEFINITION.supports_auto is False
    assert DEFINITION.allowed_policies() == frozenset({"approval"})
    assert DEFINITION.presentation.approval_prompt is not None
    assert (
        "asks Google to remove the page from its index" in DEFINITION.presentation.approval_prompt
    )
    assert "returns 404 or 410" in DEFINITION.presentation.approval_prompt
    assert "noindex directive" in DEFINITION.presentation.approval_prompt
    monkeypatch.setattr(
        "integrations.google_search_console.settings.google_search_console_settings.GOOGLE_SEARCH_CONSOLE_INDEXING_API_ENABLED",
        False,
    )
    assert DEFINITION.availability_check is not None
    assert DEFINITION.availability_check() is False
    monkeypatch.setattr(
        "integrations.google_search_console.settings.google_search_console_settings.GOOGLE_SEARCH_CONSOLE_INDEXING_API_ENABLED",
        True,
    )
    assert DEFINITION.availability_check() is True
