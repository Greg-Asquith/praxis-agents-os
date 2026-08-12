# apps/api/tests/routes/audit_events/test_audit_event_routes.py

"""HTTP-boundary tests for workspace audit-event routes."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx2 import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from core.database import get_maintenance_async_db_session_factory
from models.audit_event import AuditEvent
from models.user import User
from models.workspace import Workspace, WorkspaceRole
from services.audit_events import (
    AuditAction,
    AuditActorType,
    AuditResourceType,
    AuditStatus,
    IntegrationOperationChange,
    IntegrationOperationCounts,
    IntegrationOperationDetail,
    IntegrationOperationTarget,
    record_integration_operation_audit_event,
)
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.support.auth import bearer_headers

pytestmark = pytest.mark.asyncio


async def _authenticated_workspace(
    db: AsyncSession,
    *,
    role: WorkspaceRole = WorkspaceRole.OWNER,
    workspace: Workspace | None = None,
) -> tuple[User, Workspace, dict[str, str]]:
    user = build_user(email=f"audit-{uuid4().hex}@example.com")
    workspace = workspace or build_workspace(slug=f"audit-{uuid4().hex[:8]}")
    membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=user.id,
        role=role,
    )
    db.add_all([user, workspace, membership])
    await db.flush()
    user.default_workspace_id = workspace.id
    session = await session_manager.create_session(db, str(user.id))
    await db.commit()
    return user, workspace, bearer_headers(session["session_token"])


async def _seed_audit_event(
    db: AsyncSession,
    *,
    workspace: Workspace | None,
    actor: User | None,
    action: AuditAction = AuditAction.CREATE,
    resource_type: AuditResourceType | str = AuditResourceType.AGENT,
    resource_id: str | None = None,
    status: AuditStatus = AuditStatus.SUCCESS,
    occurred_at: datetime | None = None,
    details: dict[str, object] | None = None,
    tool_name: str | None = None,
    tool_provider: str | None = None,
) -> AuditEvent:
    event = AuditEvent(
        workspace_id=workspace.id if workspace else None,
        occurred_at=occurred_at or datetime.now(UTC),
        action=action.value,
        resource_type=resource_type.value
        if isinstance(resource_type, AuditResourceType)
        else resource_type,
        resource_id=resource_id or str(uuid4()),
        status=status.value,
        summary=f"{action.value} audit event",
        tool_name=tool_name,
        tool_provider=tool_provider,
        actor_type=AuditActorType.USER.value if actor else AuditActorType.SYSTEM.value,
        actor_id=str(actor.id) if actor else None,
        actor_user_id=actor.id if actor else None,
        actor_display=actor.email if actor else "System",
        requested_by_user_id=actor.id if actor else None,
        details=details or {"seed": True},
        request_id=f"req-{uuid4().hex[:8]}",
        ip_address="127.0.0.1",
        user_agent="pytest",
    )
    db.add(event)
    await db.flush()
    return event


async def test_audit_event_list_authorization_matrix(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    owner, workspace, owner_headers = await _authenticated_workspace(db_session)
    _admin, _workspace, admin_headers = await _authenticated_workspace(
        db_session,
        role=WorkspaceRole.ADMIN,
        workspace=workspace,
    )
    _member, _workspace, member_headers = await _authenticated_workspace(
        db_session,
        role=WorkspaceRole.MEMBER,
        workspace=workspace,
    )
    _read_only, _workspace, read_only_headers = await _authenticated_workspace(
        db_session,
        role=WorkspaceRole.READ_ONLY,
        workspace=workspace,
    )
    await _seed_audit_event(db_session, workspace=workspace, actor=owner)
    await db_session.commit()

    owner_response = await db_async_client.get("/api/v1/audit-events/", headers=owner_headers)
    assert owner_response.status_code == 200
    assert owner_response.json()["total"] == 1

    admin_response = await db_async_client.get("/api/v1/audit-events/", headers=admin_headers)
    assert admin_response.status_code == 200
    assert admin_response.json()["total"] == 1

    member_response = await db_async_client.get("/api/v1/audit-events/", headers=member_headers)
    assert member_response.status_code == 403
    assert member_response.headers["content-type"].startswith("application/problem+json")

    read_only_response = await db_async_client.get(
        "/api/v1/audit-events/",
        headers=read_only_headers,
    )
    assert read_only_response.status_code == 403
    assert read_only_response.headers["content-type"].startswith("application/problem+json")

    unauthenticated_response = await db_async_client.get("/api/v1/audit-events/")
    assert unauthenticated_response.status_code == 401
    assert unauthenticated_response.headers["content-type"].startswith("application/problem+json")


async def test_audit_event_list_is_workspace_scoped(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, workspace_a, headers = await _authenticated_workspace(db_session)
    workspace_b = build_workspace(slug=f"audit-other-{uuid4().hex[:8]}")
    db_session.add(workspace_b)
    await db_session.flush()
    visible = await _seed_audit_event(
        db_session,
        workspace=workspace_a,
        actor=user,
        action=AuditAction.UPDATE,
        resource_type=AuditResourceType.AGENT,
        resource_id="same-shaped-resource",
    )
    hidden = await _seed_audit_event(
        db_session,
        workspace=workspace_b,
        actor=user,
        action=AuditAction.UPDATE,
        resource_type=AuditResourceType.AGENT,
        resource_id="same-shaped-resource",
    )
    await db_session.commit()

    response = await db_async_client.get("/api/v1/audit-events/", headers=headers)

    assert response.status_code == 200
    event_ids = {event["id"] for event in response.json()["events"]}
    assert str(visible.id) in event_ids
    assert str(hidden.id) not in event_ids


async def test_audit_event_filters_narrow_results(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    actor, workspace, headers = await _authenticated_workspace(db_session)
    other_actor = build_user(email=f"audit-other-actor-{uuid4().hex}@example.com")
    db_session.add(other_actor)
    await db_session.flush()
    base_time = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
    matching = await _seed_audit_event(
        db_session,
        workspace=workspace,
        actor=actor,
        action=AuditAction.DELETE,
        resource_type=AuditResourceType.AGENT_SCHEDULE,
        resource_id="schedule-1",
        status=AuditStatus.DENIED,
        occurred_at=base_time,
    )
    await _seed_audit_event(
        db_session,
        workspace=workspace,
        actor=other_actor,
        action=AuditAction.UPDATE,
        resource_type=AuditResourceType.AGENT,
        resource_id="agent-1",
        status=AuditStatus.SUCCESS,
        occurred_at=base_time - timedelta(days=3),
    )
    await _seed_audit_event(
        db_session,
        workspace=workspace,
        actor=actor,
        action=AuditAction.DELETE,
        resource_type=AuditResourceType.AGENT_SCHEDULE,
        resource_id="schedule-2",
        status=AuditStatus.DENIED,
        occurred_at=base_time + timedelta(days=3),
    )
    await db_session.commit()

    response = await db_async_client.get(
        "/api/v1/audit-events/",
        headers=headers,
        params={
            "action": "delete",
            "resource_type": "agent_schedule",
            "status": "denied",
            "actor_user_id": str(actor.id),
            "occurred_after": (base_time - timedelta(hours=1)).isoformat(),
            "occurred_before": (base_time + timedelta(hours=1)).isoformat(),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["events"][0]["id"] == str(matching.id)


async def test_audit_event_filter_rejects_unknown_action(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    _user, _workspace, headers = await _authenticated_workspace(db_session)

    response = await db_async_client.get(
        "/api/v1/audit-events/",
        headers=headers,
        params={"action": "typo"},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["field"] == "action"
    assert "create" in body["allowed_values"]


async def test_audit_event_tool_filters_are_exact_combined_and_workspace_scoped(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    actor, workspace, headers = await _authenticated_workspace(db_session)
    other_workspace = build_workspace(slug=f"audit-tool-other-{uuid4().hex[:8]}")
    db_session.add(other_workspace)
    await db_session.flush()
    base_time = datetime(2026, 2, 10, 12, 0, tzinfo=UTC)
    matching = await _seed_audit_event(
        db_session,
        workspace=workspace,
        actor=actor,
        action=AuditAction.EXECUTE,
        resource_type=AuditResourceType.TOOL_CALL,
        status=AuditStatus.SUCCESS,
        occurred_at=base_time,
        tool_name="gmail_search_messages",
        tool_provider="gmail",
    )
    other_tool = await _seed_audit_event(
        db_session,
        workspace=workspace,
        actor=actor,
        action=AuditAction.EXECUTE,
        resource_type=AuditResourceType.TOOL_CALL,
        status=AuditStatus.SUCCESS,
        occurred_at=base_time,
        tool_name="gmail_search_messages_extended",
        tool_provider="gmail",
    )
    other_provider = await _seed_audit_event(
        db_session,
        workspace=workspace,
        actor=actor,
        action=AuditAction.EXECUTE,
        resource_type=AuditResourceType.TOOL_CALL,
        status=AuditStatus.SUCCESS,
        occurred_at=base_time,
        tool_name="gmail_search_messages",
        tool_provider="custom_gmail",
    )
    hidden = await _seed_audit_event(
        db_session,
        workspace=other_workspace,
        actor=actor,
        action=AuditAction.EXECUTE,
        resource_type=AuditResourceType.TOOL_CALL,
        status=AuditStatus.SUCCESS,
        occurred_at=base_time,
        tool_name="gmail_search_messages",
        tool_provider="gmail",
    )
    await db_session.commit()

    tool_response = await db_async_client.get(
        "/api/v1/audit-events/",
        headers=headers,
        params={"tool_name": "gmail_search_messages"},
    )
    assert tool_response.status_code == 200
    assert {event["id"] for event in tool_response.json()["events"]} == {
        str(matching.id),
        str(other_provider.id),
    }

    provider_response = await db_async_client.get(
        "/api/v1/audit-events/",
        headers=headers,
        params={"tool_provider": "gmail"},
    )
    assert provider_response.status_code == 200
    assert {event["id"] for event in provider_response.json()["events"]} == {
        str(matching.id),
        str(other_tool.id),
    }

    combined_response = await db_async_client.get(
        "/api/v1/audit-events/",
        headers=headers,
        params={
            "action": "execute",
            "status": "success",
            "occurred_after": (base_time - timedelta(minutes=1)).isoformat(),
            "occurred_before": (base_time + timedelta(minutes=1)).isoformat(),
            "tool_name": "gmail_search_messages",
            "tool_provider": "gmail",
        },
    )
    assert combined_response.status_code == 200
    body = combined_response.json()
    assert body["total"] == 1
    assert body["events"][0]["id"] == str(matching.id)
    assert body["events"][0]["id"] != str(hidden.id)

    unmatched_response = await db_async_client.get(
        "/api/v1/audit-events/",
        headers=headers,
        params={"tool_name": "gmail_search_message"},
    )
    assert unmatched_response.status_code == 200
    assert unmatched_response.json()["events"] == []
    assert unmatched_response.json()["total"] == 0


async def test_audit_event_list_rolls_up_before_pagination_and_uses_provider_status(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    actor, workspace, headers = await _authenticated_workspace(db_session)
    tool_call_id = "call-negative-keywords"
    base_time = datetime(2026, 2, 11, 12, 0, tzinfo=UTC)
    await _seed_audit_event(
        db_session,
        workspace=workspace,
        actor=actor,
        action=AuditAction.EXECUTE,
        resource_type=AuditResourceType.TOOL_CALL,
        resource_id=tool_call_id,
        status=AuditStatus.PENDING,
        occurred_at=base_time,
        details={"run_id": "run-1"},
        tool_name="google_ads_add_negative_keywords",
        tool_provider="google_ads",
    )
    completed = await _seed_audit_event(
        db_session,
        workspace=workspace,
        actor=actor,
        action=AuditAction.EXECUTE,
        resource_type=AuditResourceType.TOOL_CALL,
        resource_id=tool_call_id,
        status=AuditStatus.SUCCESS,
        occurred_at=base_time + timedelta(seconds=2),
        details={"run_id": "run-1"},
        tool_name="google_ads_add_negative_keywords",
        tool_provider="google_ads",
    )
    provider_failure = await _seed_audit_event(
        db_session,
        workspace=workspace,
        actor=actor,
        action=AuditAction.EXECUTE,
        resource_type=AuditResourceType.INTEGRATION_RESOURCE,
        resource_id="resource-1",
        status=AuditStatus.FAILURE,
        occurred_at=base_time + timedelta(seconds=1),
        details={"run_id": "run-1", "tool_call_id": tool_call_id},
        tool_name="google_ads_add_negative_keywords",
        tool_provider="google_ads",
    )
    unrelated = await _seed_audit_event(
        db_session,
        workspace=workspace,
        actor=actor,
        occurred_at=base_time - timedelta(seconds=1),
    )
    await db_session.commit()

    first_page = await db_async_client.get(
        "/api/v1/audit-events/", headers=headers, params={"limit": 1, "offset": 0}
    )
    second_page = await db_async_client.get(
        "/api/v1/audit-events/", headers=headers, params={"limit": 1, "offset": 1}
    )

    assert first_page.status_code == 200
    assert second_page.status_code == 200
    assert first_page.json()["total"] == 2
    assert second_page.json()["total"] == 2
    rolled_up = first_page.json()["events"][0]
    assert rolled_up["id"] == str(completed.id)
    assert rolled_up["detail_event_id"] == str(provider_failure.id)
    assert rolled_up["status"] == "failure"
    assert rolled_up["summary"] == provider_failure.summary
    assert second_page.json()["events"][0]["id"] == str(unrelated.id)


async def test_audit_event_rollup_filters_qualify_complete_groups_from_members(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    actor, workspace, headers = await _authenticated_workspace(db_session)
    tool_call_id = "call-filtered-negative-keywords"
    integration_resource_id = "resource-filtered"
    base_time = datetime(2026, 2, 12, 12, 0, tzinfo=UTC)
    await _seed_audit_event(
        db_session,
        workspace=workspace,
        actor=actor,
        action=AuditAction.EXECUTE,
        resource_type=AuditResourceType.TOOL_CALL,
        resource_id=tool_call_id,
        status=AuditStatus.PENDING,
        occurred_at=base_time,
        details={"run_id": "run-filtered"},
        tool_name="google_ads_add_negative_keywords",
        tool_provider="google_ads",
    )
    completed = await _seed_audit_event(
        db_session,
        workspace=workspace,
        actor=actor,
        action=AuditAction.EXECUTE,
        resource_type=AuditResourceType.TOOL_CALL,
        resource_id=tool_call_id,
        status=AuditStatus.SUCCESS,
        occurred_at=base_time + timedelta(seconds=2),
        details={"run_id": "run-filtered"},
        tool_name="google_ads_add_negative_keywords",
        tool_provider="google_ads",
    )
    provider_failure = await _seed_audit_event(
        db_session,
        workspace=workspace,
        actor=actor,
        action=AuditAction.UPDATE,
        resource_type=AuditResourceType.INTEGRATION_RESOURCE,
        resource_id=integration_resource_id,
        status=AuditStatus.FAILURE,
        occurred_at=base_time + timedelta(seconds=1),
        details={"run_id": "run-filtered", "tool_call_id": tool_call_id},
        tool_name="google_ads_add_negative_keywords",
        tool_provider="google_ads",
    )
    await _seed_audit_event(
        db_session,
        workspace=workspace,
        actor=actor,
        occurred_at=base_time - timedelta(seconds=1),
    )
    await db_session.commit()

    async def get_events(**params: str | int) -> dict[str, object]:
        response = await db_async_client.get(
            "/api/v1/audit-events/",
            headers=headers,
            params=params,
        )
        assert response.status_code == 200
        return response.json()

    expected_rollup = {
        "display_id": str(completed.id),
        "detail_event_id": str(provider_failure.id),
        "status": "failure",
    }

    for params in (
        {"resource_type": "integration_resource"},
        {"resource_id": integration_resource_id},
        {
            "resource_type": "integration_resource",
            "resource_id": integration_resource_id,
        },
        {"resource_type": "tool_call"},
        {"resource_id": tool_call_id},
        {"resource_type": "tool_call", "resource_id": tool_call_id},
        {
            "occurred_after": (base_time + timedelta(milliseconds=500)).isoformat(),
            "occurred_before": (base_time + timedelta(milliseconds=1500)).isoformat(),
        },
        {"status": "failure"},
        {
            "resource_type": "integration_resource",
            "resource_id": integration_resource_id,
            "actor_user_id": str(actor.id),
            "action": "update",
            "tool_name": "google_ads_add_negative_keywords",
            "tool_provider": "google_ads",
            "occurred_after": (base_time + timedelta(milliseconds=500)).isoformat(),
            "occurred_before": (base_time + timedelta(milliseconds=1500)).isoformat(),
            "status": "failure",
        },
    ):
        body = await get_events(**params)
        assert body["total"] == 1
        event = body["events"][0]
        assert event["id"] == expected_rollup["display_id"]
        assert event["detail_event_id"] == expected_rollup["detail_event_id"]
        assert event["status"] == expected_rollup["status"]

    mismatched = await get_events(
        resource_type="integration_resource",
        resource_id=tool_call_id,
    )
    assert mismatched["events"] == []
    assert mismatched["total"] == 0

    display_status = await get_events(status="success", resource_id=tool_call_id)
    assert display_status["events"] == []
    assert display_status["total"] == 0

    first_page = await get_events(resource_type="tool_call", limit=1, offset=0)
    past_end = await get_events(resource_type="tool_call", limit=1, offset=1)
    assert first_page["total"] == 1
    assert first_page["events"][0]["id"] == str(completed.id)
    assert past_end["total"] == 1
    assert past_end["events"] == []


async def test_audit_event_rollup_scopes_reused_tool_call_ids_to_the_run(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    actor, workspace, headers = await _authenticated_workspace(db_session)
    tool_call_id = "call-reused-across-runs"
    base_time = datetime(2026, 2, 13, 12, 0, tzinfo=UTC)
    expected: dict[str, dict[str, str]] = {}

    for index, (run_id, provider_status) in enumerate(
        (("run-success", AuditStatus.SUCCESS), ("run-failure", AuditStatus.FAILURE))
    ):
        occurred_at = base_time + timedelta(minutes=index)
        completed = await _seed_audit_event(
            db_session,
            workspace=workspace,
            actor=actor,
            action=AuditAction.EXECUTE,
            resource_type=AuditResourceType.TOOL_CALL,
            resource_id=tool_call_id,
            status=AuditStatus.SUCCESS,
            occurred_at=occurred_at + timedelta(seconds=1),
            details={"run_id": run_id},
            tool_name="google_ads_add_negative_keywords",
            tool_provider="google_ads",
        )
        provider_event = await _seed_audit_event(
            db_session,
            workspace=workspace,
            actor=actor,
            action=AuditAction.EXECUTE,
            resource_type=AuditResourceType.INTEGRATION_RESOURCE,
            resource_id=f"resource-{run_id}",
            status=provider_status,
            occurred_at=occurred_at,
            details={
                "run_id": run_id,
                "tool_call_id": tool_call_id,
                "operation_detail": {"run_marker": run_id},
            },
            tool_name="google_ads_add_negative_keywords",
            tool_provider="google_ads",
        )
        expected[str(completed.id)] = {
            "detail_event_id": str(provider_event.id),
            "status": provider_status.value,
            "summary": provider_event.summary,
            "run_marker": run_id,
        }
    await db_session.commit()

    response = await db_async_client.get("/api/v1/audit-events/", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert {event["id"] for event in body["events"]} == set(expected)
    for event in body["events"]:
        expected_event = expected[event["id"]]
        assert event["detail_event_id"] == expected_event["detail_event_id"]
        assert event["status"] == expected_event["status"]
        assert event["summary"] == expected_event["summary"]
        detail_response = await db_async_client.get(
            f"/api/v1/audit-events/{event['detail_event_id']}",
            headers=headers,
        )
        assert detail_response.status_code == 200
        assert (
            detail_response.json()["details"]["operation_detail"]["run_marker"]
            == (expected_event["run_marker"])
        )


async def test_audit_event_rollup_keeps_incomplete_legacy_correlation_standalone(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    actor, workspace, headers = await _authenticated_workspace(db_session)
    tool_call_id = "call-legacy-collision"
    base_time = datetime(2026, 2, 14, 12, 0, tzinfo=UTC)
    events = [
        await _seed_audit_event(
            db_session,
            workspace=workspace,
            actor=actor,
            action=AuditAction.EXECUTE,
            resource_type=AuditResourceType.TOOL_CALL,
            resource_id=tool_call_id,
            occurred_at=base_time,
            details={"legacy": True},
        ),
        await _seed_audit_event(
            db_session,
            workspace=workspace,
            actor=actor,
            action=AuditAction.EXECUTE,
            resource_type=AuditResourceType.TOOL_CALL,
            resource_id=tool_call_id,
            occurred_at=base_time + timedelta(seconds=1),
            details={"legacy": True},
        ),
        await _seed_audit_event(
            db_session,
            workspace=workspace,
            actor=actor,
            action=AuditAction.EXECUTE,
            resource_type=AuditResourceType.INTEGRATION_RESOURCE,
            resource_id="resource-without-run",
            occurred_at=base_time + timedelta(seconds=2),
            details={"tool_call_id": tool_call_id},
        ),
        await _seed_audit_event(
            db_session,
            workspace=workspace,
            actor=actor,
            action=AuditAction.EXECUTE,
            resource_type=AuditResourceType.INTEGRATION_RESOURCE,
            resource_id="resource-without-call",
            occurred_at=base_time + timedelta(seconds=3),
            details={"run_id": "run-without-call"},
        ),
    ]
    await db_session.commit()

    response = await db_async_client.get("/api/v1/audit-events/", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == len(events)
    assert {event["id"] for event in body["events"]} == {str(event.id) for event in events}
    assert all(event["id"] == event["detail_event_id"] for event in body["events"])


async def test_integration_operation_audit_persists_and_round_trips_full_detail(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    actor, workspace, headers = await _authenticated_workspace(db_session)
    detail = IntegrationOperationDetail(
        target=IntegrationOperationTarget(
            entity_type="google_ads_shared_set",
            external_id="50",
            display_name="Brand Protection",
            integration_resource_id=str(uuid4()),
        ),
        changes=[
            IntegrationOperationChange(
                action="add",
                entity_type="negative_keyword",
                external_ref="customers/111/sharedCriteria/50~1",
                fields={"text": "Brand Term", "match_type": "EXACT"},
            )
        ],
        counts=IntegrationOperationCounts(applied=1, skipped=0, failed=0),
    )
    event_id = await record_integration_operation_audit_event(
        workspace_id=workspace.id,
        agent=SimpleNamespace(id=uuid4(), name="Ads operator"),
        run=SimpleNamespace(id=uuid4(), user_id=actor.id),
        tool_call_id="call-persisted-detail",
        tool_name="google_ads_add_negative_keywords",
        provider_key="google_ads",
        connection_id=uuid4(),
        integration_resource_id=uuid4(),
        external_id="111",
        operation="add_negative_keywords",
        status=AuditStatus.SUCCESS,
        external_ref="customers/111/sharedCriteria/50~1",
        error_code=None,
        operation_detail=detail,
        raise_on_error=True,
    )

    assert event_id is not None
    response = await db_async_client.get(f"/api/v1/audit-events/{event_id}", headers=headers)
    assert response.status_code == 200
    stored = response.json()
    assert stored["detail_event_id"] == str(event_id)
    assert stored["details"]["operation_detail"] == detail.model_dump(mode="json")


async def test_audit_roll_up_keeps_pending_provider_evidence_when_finalization_fails(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    actor, workspace, headers = await _authenticated_workspace(db_session)
    tool_call_id = "call-with-pending-evidence"
    base_time = datetime(2026, 2, 12, 12, 0, tzinfo=UTC)
    pending_provider = await _seed_audit_event(
        db_session,
        workspace=workspace,
        actor=actor,
        action=AuditAction.EXECUTE,
        resource_type=AuditResourceType.INTEGRATION_RESOURCE,
        resource_id="resource-1",
        status=AuditStatus.PENDING,
        occurred_at=base_time,
        details={
            "run_id": "run-2",
            "tool_call_id": tool_call_id,
            "operation_detail": {"schema_version": 1},
        },
        tool_name="google_ads_add_negative_keywords",
        tool_provider="google_ads",
    )
    tool_failure = await _seed_audit_event(
        db_session,
        workspace=workspace,
        actor=actor,
        action=AuditAction.EXECUTE,
        resource_type=AuditResourceType.TOOL_CALL,
        resource_id=tool_call_id,
        status=AuditStatus.FAILURE,
        occurred_at=base_time + timedelta(seconds=1),
        details={"run_id": "run-2"},
        tool_name="google_ads_add_negative_keywords",
        tool_provider="google_ads",
    )
    await db_session.commit()

    response = await db_async_client.get("/api/v1/audit-events/", headers=headers)

    assert response.status_code == 200
    assert response.json()["total"] == 1
    rolled_up = response.json()["events"][0]
    assert rolled_up["id"] == str(tool_failure.id)
    assert rolled_up["detail_event_id"] == str(pending_provider.id)
    assert rolled_up["status"] == "failure"
    assert rolled_up["summary"] == tool_failure.summary


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tool_name", "t" * 101),
        ("tool_provider", "p" * 51),
    ],
)
async def test_audit_event_tool_filters_reject_overlong_values(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    field: str,
    value: str,
) -> None:
    _user, _workspace, headers = await _authenticated_workspace(db_session)

    response = await db_async_client.get(
        "/api/v1/audit-events/",
        headers=headers,
        params={field: value},
    )

    assert response.status_code == 422


async def test_audit_event_detail_scoping_and_system_visibility(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, workspace_a, headers = await _authenticated_workspace(db_session)
    workspace_b = build_workspace(slug=f"audit-detail-other-{uuid4().hex[:8]}")
    db_session.add(workspace_b)
    await db_session.flush()
    visible = await _seed_audit_event(
        db_session,
        workspace=workspace_a,
        actor=user,
        details={"field": "value"},
    )
    hidden = await _seed_audit_event(db_session, workspace=workspace_b, actor=user)
    async with get_maintenance_async_db_session_factory()() as maintenance_db:
        system_event = await _seed_audit_event(maintenance_db, workspace=None, actor=None)
        await maintenance_db.commit()
    await db_session.commit()

    detail_response = await db_async_client.get(
        f"/api/v1/audit-events/{visible.id}",
        headers=headers,
    )
    assert detail_response.status_code == 200
    assert detail_response.json()["details"] == {"field": "value"}

    cross_workspace_response = await db_async_client.get(
        f"/api/v1/audit-events/{hidden.id}",
        headers=headers,
    )
    assert cross_workspace_response.status_code == 404

    system_detail_response = await db_async_client.get(
        f"/api/v1/audit-events/{system_event.id}",
        headers=headers,
    )
    assert system_detail_response.status_code == 404

    list_response = await db_async_client.get("/api/v1/audit-events/", headers=headers)
    assert str(system_event.id) not in {event["id"] for event in list_response.json()["events"]}
