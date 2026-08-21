"""Published integration-operation runtime recipe and contract tests."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx2
import pytest

from core.exceptions.integration import (
    IntegrationConnectionError,
    IntegrationError,
    IntegrationFailureDisposition,
)
from core.settings import settings
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_EXTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_EGRESS_EXTERNAL_WRITE,
    TOOL_EGRESS_PROVIDER_QUERY,
    TOOL_POLICY_APPROVAL,
    IntegrationToolBinding,
    RuntimeToolDefinition,
    validate_definition,
)
from services.agents.runtime.tools.registry import (
    RUNTIME_TOOL_CATALOG,
    register_tool_definition,
)
from services.audit_events import (
    AuditStatus,
    IntegrationOperationCounts,
    IntegrationOperationEffect,
    IntegrationOperationIntent,
    IntegrationOperationIntentGroup,
    IntegrationOperationOutcome,
    IntegrationOperationOutcomeGroup,
    IntegrationOperationTarget,
    PendingIntegrationOperationDetail,
    TerminalIntegrationOperationDetail,
    terminal_applied_operation_detail,
)
from services.integrations import http as integration_http
from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry
from services.integrations.context.fan_out import run_context_fan_out
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.http import IntegrationRequestPolicy
from services.integrations.manifest import PROVIDER_MANIFESTS, IntegrationProviderManifest
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

READ_TOOL = "test_provider_read"
WRITE_TOOL = "test_provider_write"
READ_BINDING = IntegrationToolBinding(
    provider_keys=frozenset({"test_provider"}),
    resource_types=frozenset({"test_resource"}),
)
WRITE_BINDING = IntegrationToolBinding(
    provider_keys=READ_BINDING.provider_keys,
    resource_types=READ_BINDING.resource_types,
    requires_write=True,
)


def _entry() -> ResolvedContextEntry:
    return ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="test_provider",
        resource_type="test_resource",
        external_id="resource-1",
        display_name="Resource One",
        connection_id=uuid4(),
        connection_label="Test connection",
        connection_status="active",
        write_allowed=True,
    )


def _ctx(
    entry: ResolvedContextEntry,
    tool_name: str,
    *,
    events: list[str] | None = None,
):
    return SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(entry,)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
            events=events,
        ),
        tool_name=tool_name,
        tool_call_id="recipe-call",
    )


def _pending_detail(entry: ResolvedContextEntry) -> PendingIntegrationOperationDetail:
    return PendingIntegrationOperationDetail(
        target=IntegrationOperationTarget(
            entity_type="test_resource",
            external_id=entry.external_id,
            integration_resource_id=str(entry.integration_resource_id),
        ),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key="records:create",
                action="create",
                entity_type="test_record",
                items=[IntegrationOperationIntent(fields={"record_count": 1})],
            )
        ],
    )


def _unverified_detail(entry: ResolvedContextEntry) -> TerminalIntegrationOperationDetail:
    pending = _pending_detail(entry)
    return TerminalIntegrationOperationDetail(
        target=pending.target,
        intent_groups=pending.intent_groups,
        outcome_groups=[
            IntegrationOperationOutcomeGroup(
                key="records:create",
                outcomes=[
                    IntegrationOperationOutcome(
                        intent_index=0,
                        status="unverified",
                        effects=[
                            IntegrationOperationEffect(
                                status="unverified",
                                error_code="UNKNOWN_RESULT",
                            )
                        ],
                    )
                ],
            )
        ],
        intent_counts=IntegrationOperationCounts(
            applied=0,
            skipped=0,
            failed=0,
            unverified=1,
        ),
        effect_counts=IntegrationOperationCounts(
            applied=0,
            skipped=0,
            failed=0,
            unverified=1,
        ),
    )


async def _synthetic_read(ctx):
    async def operation(entry: ResolvedContextEntry):
        async def execute():
            return IntegrationAuditOutcome({"value": entry.external_id})

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name=READ_TOOL,
            operation="read",
            execute=execute,
        )

    results = await run_context_fan_out(ctx, binding=READ_BINDING, operation=operation)
    return {"results": serialize_fan_out_results(results)}


async def _synthetic_write(ctx):
    async def operation(entry: ResolvedContextEntry):
        pending_detail = _pending_detail(entry)

        async def execute():
            if ctx.deps.events is not None:
                ctx.deps.events.append("provider")
            return IntegrationAuditOutcome(
                {"created": 1},
                external_ref="record-1",
                operation_detail=terminal_applied_operation_detail(
                    pending_detail,
                    external_ref="record-1",
                ),
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name=WRITE_TOOL,
            operation="write",
            execute=execute,
            pending_operation_detail=pending_detail,
        )

    results = await run_context_fan_out(ctx, binding=WRITE_BINDING, operation=operation)
    return {"results": serialize_fan_out_results(results)}


@pytest.fixture
def synthetic_provider():
    manifests_before = dict(PROVIDER_MANIFESTS)
    catalog_before = dict(RUNTIME_TOOL_CATALOG)
    PROVIDER_MANIFESTS["test_provider"] = IntegrationProviderManifest(
        provider_key="test_provider",
        display_name="Test Provider",
        auth_modes=("api_key",),
        owner_scope="workspace",
        resource_types=("test_resource",),
        required_form_fields=("api_key",),
    )
    register_tool_definition(
        RuntimeToolDefinition(
            name=READ_TOOL,
            function=_synthetic_read,
            description="Read one synthetic resource.",
            provider="test_provider",
            egress=TOOL_EGRESS_PROVIDER_QUERY,
            takes_ctx=True,
            integration_binding=READ_BINDING,
        )
    )
    register_tool_definition(
        RuntimeToolDefinition(
            name=WRITE_TOOL,
            function=_synthetic_write,
            description="Write one synthetic resource.",
            provider="test_provider",
            effect=TOOL_EFFECT_WRITE,
            effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
            egress=TOOL_EGRESS_EXTERNAL_WRITE,
            default_policy=TOOL_POLICY_APPROVAL,
            supports_auto=False,
            takes_ctx=True,
            integration_binding=WRITE_BINDING,
        )
    )
    yield
    PROVIDER_MANIFESTS.clear()
    PROVIDER_MANIFESTS.update(manifests_before)
    RUNTIME_TOOL_CATALOG.clear()
    RUNTIME_TOOL_CATALOG.update(catalog_before)


async def test_suite_local_provider_read_and_write_follow_the_published_recipe(
    synthetic_provider, monkeypatch
) -> None:
    events: list[str] = []

    async def audit(**kwargs):
        events.append(kwargs["status"].value)
        return uuid4()

    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    entry = _entry()

    read = await _synthetic_read(_ctx(entry, READ_TOOL))
    write = await _synthetic_write(_ctx(entry, WRITE_TOOL, events=events))

    assert read["results"][0]["data"] == {"value": "resource-1"}
    assert write["results"][0]["data"] == {"created": 1}
    assert events == ["success", "pending", "provider", "success"]


async def test_terminal_audit_records_latency_and_transport_attempts(
    synthetic_provider, monkeypatch
) -> None:
    recorded: list[dict] = []

    async def audit(**kwargs):
        recorded.append(kwargs)
        return uuid4()

    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    monkeypatch.setattr(settings, "INTEGRATIONS_HTTP_RETRY_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(integration_http.asyncio, "sleep", AsyncMock())
    responses = iter([503, 200])

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(next(responses, 200), request=request)

    entry = _entry()
    ctx = _ctx(entry, READ_TOOL)

    async def execute():
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
            await integration_http.request_with_retries(
                "GET",
                "https://provider.example/resource",
                operation="read",
                provider_key="test_provider",
                policy=IntegrationRequestPolicy.READ,
                client=client,
            )
        return IntegrationAuditOutcome({"value": entry.external_id})

    value = await run_audited_integration_operation(
        ctx, entry, tool_name=READ_TOOL, operation="read", execute=execute
    )

    assert value == {"value": "resource-1"}
    [terminal] = recorded
    assert terminal["status"] is AuditStatus.SUCCESS
    assert terminal["latency_ms"] >= 1
    assert terminal["http_requests"] == 1
    assert terminal["http_attempts"] == 2

    recorded.clear()

    async def execute_without_transport():
        return IntegrationAuditOutcome({"value": entry.external_id})

    await run_audited_integration_operation(
        ctx, entry, tool_name=READ_TOOL, operation="read", execute=execute_without_transport
    )
    [terminal] = recorded
    assert terminal["latency_ms"] >= 1
    assert terminal["http_requests"] is None
    assert terminal["http_attempts"] is None

    recorded.clear()

    async def execute_failure():
        async with httpx2.AsyncClient(
            transport=httpx2.MockTransport(lambda request: httpx2.Response(503, request=request))
        ) as client:
            await integration_http.request_with_retries(
                "GET",
                "https://provider.example/resource",
                operation="read",
                provider_key="test_provider",
                policy=IntegrationRequestPolicy.READ,
                client=client,
            )
        raise AssertionError("unreachable")

    with pytest.raises(IntegrationConnectionError):
        await run_audited_integration_operation(
            ctx, entry, tool_name=READ_TOOL, operation="read", execute=execute_failure
        )
    [terminal] = recorded
    assert terminal["status"] is AuditStatus.FAILURE
    assert terminal["latency_ms"] >= 1
    assert terminal["http_requests"] == 1
    assert terminal["http_attempts"] == 3


async def test_external_write_cannot_disable_durable_evidence(synthetic_provider) -> None:
    entry = _entry()
    called = False

    async def execute():
        nonlocal called
        called = True
        return IntegrationAuditOutcome(None)

    with pytest.raises(ValueError, match="require pending operation detail"):
        await run_audited_integration_operation(
            _ctx(entry, WRITE_TOOL),
            entry,
            tool_name=WRITE_TOOL,
            operation="write",
            execute=execute,
        )

    assert called is False


async def test_operation_rejects_provider_binding_mismatch(synthetic_provider) -> None:
    entry = _entry()
    mismatched = ResolvedContextEntry(
        **{**entry.__dict__, "provider_key": "gmail", "resource_type": "gmail_mailbox"}
    )

    with pytest.raises(RuntimeError, match="registered provider binding"):
        await run_audited_integration_operation(
            _ctx(entry, READ_TOOL),
            mismatched,
            tool_name=READ_TOOL,
            operation="read",
            execute=lambda: None,  # type: ignore[arg-type]
        )


async def test_operation_rejects_tool_name_that_does_not_match_dispatch(
    synthetic_provider,
) -> None:
    entry = _entry()
    execute = AsyncMock()

    with pytest.raises(RuntimeError, match="does not match the dispatched tool"):
        await run_audited_integration_operation(
            _ctx(entry, WRITE_TOOL),
            entry,
            tool_name=READ_TOOL,
            operation="read",
            execute=execute,
        )

    execute.assert_not_awaited()


async def test_operation_rejects_non_terminal_outcome_status(
    synthetic_provider,
    monkeypatch,
) -> None:
    entry = _entry()
    pending_event_id = uuid4()
    audit = AsyncMock(return_value=pending_event_id)
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )

    async def execute():
        return IntegrationAuditOutcome(None, status="pending")  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="terminal status"):
        await run_audited_integration_operation(
            _ctx(entry, WRITE_TOOL),
            entry,
            tool_name=WRITE_TOOL,
            operation="write",
            execute=execute,
            pending_operation_detail=_pending_detail(entry),
        )

    assert [call.kwargs["status"] for call in audit.await_args_list] == [
        "pending",
        "failure",
    ]
    assert audit.await_args_list[1].kwargs["related_event_id"] == pending_event_id


async def test_unverified_outcome_is_persisted_before_outer_failure(
    synthetic_provider,
    monkeypatch,
) -> None:
    entry = _entry()
    pending_event_id = uuid4()
    audit = AsyncMock(return_value=pending_event_id)
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )
    detail = _unverified_detail(entry)

    async def execute():
        return IntegrationAuditOutcome(
            {"created": 0},
            status=AuditStatus.UNVERIFIED,
            operation_detail=detail,
        )

    with pytest.raises(IntegrationError) as exc_info:
        await run_audited_integration_operation(
            _ctx(entry, WRITE_TOOL),
            entry,
            tool_name=WRITE_TOOL,
            operation="write",
            execute=execute,
            pending_operation_detail=_pending_detail(entry),
        )

    assert exc_info.value.failure_disposition is IntegrationFailureDisposition.AMBIGUOUS
    assert [call.kwargs["status"] for call in audit.await_args_list] == [
        AuditStatus.PENDING,
        AuditStatus.UNVERIFIED,
    ]
    assert audit.await_args_list[1].kwargs["operation_detail"] is detail
    assert audit.await_args_list[1].kwargs["related_event_id"] == pending_event_id


@pytest.mark.parametrize(
    ("disposition", "expected_error_code"),
    [
        (IntegrationFailureDisposition.NOT_DISPATCHED, "IntegrationConnectionError"),
        (IntegrationFailureDisposition.REJECTED, "IntegrationConnectionError"),
        (IntegrationFailureDisposition.AMBIGUOUS, "unverified_mutation"),
    ],
)
async def test_write_failure_disposition_controls_terminal_evidence(
    synthetic_provider,
    monkeypatch,
    disposition: IntegrationFailureDisposition,
    expected_error_code: str,
) -> None:
    entry = _entry()
    pending_event_id = uuid4()
    audit = AsyncMock(return_value=pending_event_id)
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )
    error = IntegrationConnectionError(
        "provider failed",
        failure_disposition=disposition,
    )

    async def execute():
        raise error

    with pytest.raises(IntegrationConnectionError) as exc_info:
        await run_audited_integration_operation(
            _ctx(entry, WRITE_TOOL),
            entry,
            tool_name=WRITE_TOOL,
            operation="write",
            execute=execute,
            pending_operation_detail=_pending_detail(entry),
        )

    assert exc_info.value is error
    terminal = audit.await_args_list[1].kwargs
    assert terminal["status"] == "failure"
    assert terminal["error_code"] == expected_error_code
    assert terminal["related_event_id"] == pending_event_id


async def test_unknown_write_failure_defaults_to_ambiguous(
    synthetic_provider,
    monkeypatch,
) -> None:
    entry = _entry()
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )
    error = ValueError("malformed provider response")

    async def execute():
        raise error

    with pytest.raises(ValueError) as exc_info:
        await run_audited_integration_operation(
            _ctx(entry, WRITE_TOOL),
            entry,
            tool_name=WRITE_TOOL,
            operation="write",
            execute=execute,
            pending_operation_detail=_pending_detail(entry),
        )

    assert exc_info.value is error
    assert error.failure_disposition is IntegrationFailureDisposition.AMBIGUOUS
    assert audit.await_args_list[1].kwargs["error_code"] == "unverified_mutation"


@pytest.mark.parametrize(
    ("disposition", "expected_error_code"),
    [
        (None, "CancelledError"),
        (IntegrationFailureDisposition.AMBIGUOUS, "unverified_mutation"),
    ],
)
async def test_write_cancellation_finalizes_correlated_evidence_and_propagates(
    synthetic_provider,
    monkeypatch,
    disposition: IntegrationFailureDisposition | None,
    expected_error_code: str,
) -> None:
    entry = _entry()
    pending_event_id = uuid4()
    audit = AsyncMock(return_value=pending_event_id)
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )

    async def execute():
        error = asyncio.CancelledError("cancelled")
        if disposition is not None:
            error.failure_disposition = disposition
        raise error

    with pytest.raises(asyncio.CancelledError):
        await run_audited_integration_operation(
            _ctx(entry, WRITE_TOOL),
            entry,
            tool_name=WRITE_TOOL,
            operation="write",
            execute=execute,
            pending_operation_detail=_pending_detail(entry),
        )

    terminal = audit.await_args_list[1].kwargs
    assert terminal["status"] == "failure"
    assert terminal["error_code"] == expected_error_code
    assert terminal["related_event_id"] == pending_event_id


async def test_write_cancellation_terminal_finalizer_is_bounded(
    synthetic_provider,
    monkeypatch,
) -> None:
    entry = _entry()
    pending_event_id = uuid4()
    audit_calls = 0

    async def audit(**_kwargs):
        nonlocal audit_calls
        audit_calls += 1
        if audit_calls == 1:
            return pending_event_id
        await asyncio.Event().wait()
        return None

    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )
    monkeypatch.setattr(
        "services.integrations.operations._TERMINAL_AUDIT_FINALIZE_TIMEOUT_SECONDS",
        0.01,
    )

    async def execute():
        raise asyncio.CancelledError("cancelled before transport")

    with pytest.raises(asyncio.CancelledError):
        await run_audited_integration_operation(
            _ctx(entry, WRITE_TOOL),
            entry,
            tool_name=WRITE_TOOL,
            operation="write",
            execute=execute,
            pending_operation_detail=_pending_detail(entry),
        )

    assert audit_calls == 2


@pytest.mark.parametrize(
    ("provider_result", "expected_status", "expected_error_code"),
    [
        ("success", "success", None),
        ("failure", "failure", "IntegrationConnectionError"),
    ],
)
async def test_cancellation_during_terminal_persistence_preserves_known_outcome(
    synthetic_provider,
    monkeypatch,
    provider_result: str,
    expected_status: str,
    expected_error_code: str | None,
) -> None:
    entry = _entry()
    pending_event_id = uuid4()
    terminal_started = asyncio.Event()
    release_terminal = asyncio.Event()
    persisted: list[dict] = []
    audit_calls = 0

    async def audit(**kwargs):
        nonlocal audit_calls
        audit_calls += 1
        if audit_calls == 1:
            return pending_event_id
        terminal_started.set()
        await release_terminal.wait()
        persisted.append(kwargs)
        return None

    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )

    async def execute():
        if provider_result == "failure":
            raise IntegrationConnectionError(
                "provider rejected the request",
                failure_disposition=IntegrationFailureDisposition.REJECTED,
            )
        return IntegrationAuditOutcome(
            None,
            external_ref="record-1",
            operation_detail=terminal_applied_operation_detail(
                _pending_detail(entry),
                external_ref="record-1",
            ),
        )

    task = asyncio.create_task(
        run_audited_integration_operation(
            _ctx(entry, WRITE_TOOL),
            entry,
            tool_name=WRITE_TOOL,
            operation="write",
            execute=execute,
            pending_operation_detail=_pending_detail(entry),
        )
    )
    await terminal_started.wait()
    task.cancel()
    release_terminal.set()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(persisted) == 1
    terminal = persisted[0]
    assert terminal["status"] == expected_status
    assert terminal["error_code"] == expected_error_code
    assert terminal["related_event_id"] == pending_event_id
    if provider_result == "success":
        assert terminal["external_ref"] == "record-1"


async def test_cancellation_during_terminal_persistence_is_bounded(
    synthetic_provider,
    monkeypatch,
) -> None:
    entry = _entry()
    pending_event_id = uuid4()
    terminal_started = asyncio.Event()
    audit_calls = 0

    async def audit(**_kwargs):
        nonlocal audit_calls
        audit_calls += 1
        if audit_calls == 1:
            return pending_event_id
        terminal_started.set()
        await asyncio.Event().wait()
        return None

    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )
    monkeypatch.setattr(
        "services.integrations.operations._TERMINAL_AUDIT_FINALIZE_TIMEOUT_SECONDS",
        0.01,
    )

    async def execute():
        return IntegrationAuditOutcome(None)

    task = asyncio.create_task(
        run_audited_integration_operation(
            _ctx(entry, WRITE_TOOL),
            entry,
            tool_name=WRITE_TOOL,
            operation="write",
            execute=execute,
            pending_operation_detail=_pending_detail(entry),
        )
    )
    await terminal_started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert audit_calls == 2


def test_external_write_definition_requires_write_binding(synthetic_provider) -> None:
    with pytest.raises(RuntimeError, match="require a write-required binding"):
        validate_definition(
            RuntimeToolDefinition(
                name="test_provider_unsafe_write",
                function=_synthetic_write,
                description="Unsafe synthetic write.",
                provider="test_provider",
                effect=TOOL_EFFECT_WRITE,
                effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
                egress=TOOL_EGRESS_EXTERNAL_WRITE,
                default_policy=TOOL_POLICY_APPROVAL,
                supports_auto=False,
                takes_ctx=True,
                integration_binding=READ_BINDING,
            )
        )
