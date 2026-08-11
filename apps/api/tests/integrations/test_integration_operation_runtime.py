"""Published integration-operation runtime recipe and contract tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

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
    IntegrationOperationChange,
    IntegrationOperationCounts,
    IntegrationOperationDetail,
    IntegrationOperationTarget,
)
from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry
from services.integrations.context.fan_out import run_context_fan_out
from services.integrations.context.results import serialize_fan_out_results
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


def _pending_detail(entry: ResolvedContextEntry) -> IntegrationOperationDetail:
    return IntegrationOperationDetail(
        target=IntegrationOperationTarget(
            entity_type="test_resource",
            external_id=entry.external_id,
            integration_resource_id=str(entry.integration_resource_id),
        ),
        changes=[
            IntegrationOperationChange(
                action="create",
                entity_type="test_record",
                fields={"record_count": 1},
            )
        ],
        counts=IntegrationOperationCounts(applied=0, skipped=0, failed=0),
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
        async def execute():
            if ctx.deps.events is not None:
                ctx.deps.events.append("provider")
            return IntegrationAuditOutcome({"created": 1}, external_ref="record-1")

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name=WRITE_TOOL,
            operation="write",
            execute=execute,
            pending_operation_detail=_pending_detail(entry),
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
