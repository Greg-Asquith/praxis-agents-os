# apps/api/tests/services/integrations/context/test_fan_out.py

"""Active-context fan-out behavior tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry

from core.exceptions.integration import IntegrationRateLimitError
from services.agents.runtime.tools.contract import IntegrationToolBinding
from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry
from services.integrations.context.fan_out import run_context_fan_out
from services.integrations.context.schemas import MAX_ACTIVE_CONTEXT_TARGETS


def _entry(
    name: str,
    *,
    provider_key: str = "gmail",
    resource_type: str = "gmail_mailbox",
    write_allowed: bool = True,
) -> ResolvedContextEntry:
    return ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key=provider_key,
        resource_type=resource_type,
        external_id=name.casefold(),
        display_name=name,
        connection_id=uuid4(),
        connection_label="Primary",
        connection_status="active",
        write_allowed=write_allowed,
    )


def _binding(*, requires_write: bool = False) -> IntegrationToolBinding:
    return IntegrationToolBinding(
        provider_keys=frozenset({"gmail"}),
        resource_types=frozenset({"gmail_mailbox"}),
        requires_write=requires_write,
    )


def _ctx(entries, *, tool_name: str = "gmail_search_messages"):
    return SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=entries),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        ),
        tool_name=tool_name,
        tool_call_id="test-call",
    )


async def test_fan_out_isolates_partial_failure() -> None:
    entries = (_entry("One"), _entry("Two"), _entry("Three"))
    ctx = _ctx(entries)

    async def operation(entry: ResolvedContextEntry):
        if entry.display_name == "Two":
            raise IntegrationRateLimitError("Slow down")
        return {"name": entry.display_name}

    results = await run_context_fan_out(ctx, binding=_binding(), operation=operation)

    assert [result.status for result in results] == ["success", "error", "success"]
    assert results[1].error_code == "IntegrationRateLimitError"
    assert results[2].data == {"name": "Three"}


async def test_fan_out_write_gate_does_not_call_operation(monkeypatch) -> None:
    entry = _entry(
        "Read only",
        provider_key="gmail",
        resource_type="gmail_mailbox",
        write_allowed=False,
    )
    ctx = _ctx((entry,), tool_name="gmail_send_message")
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        AsyncMock(),
    )
    calls = 0

    async def operation(_entry: ResolvedContextEntry):
        nonlocal calls
        calls += 1

    results = await run_context_fan_out(
        ctx,
        binding=IntegrationToolBinding(
            provider_keys=frozenset({"gmail"}),
            resource_types=frozenset({"gmail_mailbox"}),
            requires_write=True,
        ),
        operation=operation,
    )

    assert calls == 0
    assert results[0].error_code == "write_not_permitted"


async def test_fan_out_write_gate_records_generic_denial_evidence(monkeypatch) -> None:
    entry = _entry(
        "Read only",
        provider_key="gmail",
        resource_type="gmail_mailbox",
        write_allowed=False,
    )
    ctx = _ctx((entry,), tool_name="gmail_send_message")
    audit = AsyncMock()
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )

    results = await run_context_fan_out(
        ctx,
        binding=IntegrationToolBinding(
            provider_keys=frozenset({"gmail"}),
            resource_types=frozenset({"gmail_mailbox"}),
            requires_write=True,
        ),
        operation=lambda _entry: None,
    )

    assert audit.await_args.kwargs["tool_name"] == "gmail_send_message"
    assert audit.await_args.kwargs["operation"] == "send_message"
    assert audit.await_args.kwargs["error_code"] == "write_not_permitted"
    assert results[0].error_code == "write_not_permitted"


async def test_fan_out_retries_when_no_compatible_entries() -> None:
    ctx = _ctx(())

    with pytest.raises(ModelRetry, match="select a context"):
        await run_context_fan_out(ctx, binding=_binding(), operation=lambda _entry: None)


async def test_fan_out_calls_every_compatible_resource_and_no_incompatible_resource() -> None:
    gmail_one = _entry(
        "Inbox one",
        provider_key="gmail",
        resource_type="gmail_mailbox",
    )
    google_ads = _entry(
        "Ads account",
        provider_key="google_ads",
        resource_type="google_ads_account",
    )
    gmail_two = _entry(
        "Inbox two",
        provider_key="gmail",
        resource_type="gmail_mailbox",
    )
    ctx = _ctx((gmail_one, google_ads, gmail_two))
    calls = []

    async def operation(entry: ResolvedContextEntry):
        calls.append(entry)
        return {"resource_id": str(entry.integration_resource_id)}

    results = await run_context_fan_out(
        ctx,
        binding=IntegrationToolBinding(
            provider_keys=frozenset({"gmail"}),
            resource_types=frozenset({"gmail_mailbox"}),
        ),
        operation=operation,
    )

    assert calls == [gmail_one, gmail_two]
    assert [result.integration_resource_id for result in results] == [
        gmail_one.integration_resource_id,
        gmail_two.integration_resource_id,
    ]
    assert google_ads.integration_resource_id not in {
        result.integration_resource_id for result in results
    }


async def test_fan_out_never_exceeds_active_context_target_budget() -> None:
    entries = tuple(_entry(f"Account {index}") for index in range(MAX_ACTIVE_CONTEXT_TARGETS + 1))
    ctx = _ctx(entries)
    calls = []

    async def operation(entry: ResolvedContextEntry):
        calls.append(entry)

    results = await run_context_fan_out(ctx, binding=_binding(), operation=operation)

    assert calls == list(entries[:MAX_ACTIVE_CONTEXT_TARGETS])
    assert len(results) == MAX_ACTIVE_CONTEXT_TARGETS


async def test_fan_out_rejects_binding_that_does_not_match_dispatched_tool() -> None:
    entry = _entry("Read only", write_allowed=False)
    operation = AsyncMock()

    with pytest.raises(RuntimeError, match="binding does not match"):
        await run_context_fan_out(
            _ctx((entry,), tool_name="gmail_send_message"),
            binding=_binding(),
            operation=operation,
        )

    operation.assert_not_awaited()
