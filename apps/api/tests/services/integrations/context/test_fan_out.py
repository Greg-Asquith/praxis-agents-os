# apps/api/tests/services/integrations/context/test_fan_out.py

"""Active-context fan-out behavior tests."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry

from core.exceptions.integration import IntegrationRateLimitError
from services.agents.runtime.tools.contract import IntegrationToolBinding
from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry
from services.integrations.context.fan_out import run_context_fan_out


def _entry(name: str, *, write_allowed: bool = True) -> ResolvedContextEntry:
    return ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="test_provider",
        resource_type="test_resource",
        external_id=name.casefold(),
        display_name=name,
        connection_id=uuid4(),
        connection_label="Primary",
        connection_status="active",
        write_allowed=write_allowed,
    )


def _binding(*, requires_write: bool = False) -> IntegrationToolBinding:
    return IntegrationToolBinding(
        provider_keys=frozenset({"test_provider"}),
        resource_types=frozenset({"test_resource"}),
        requires_write=requires_write,
    )


async def test_fan_out_isolates_partial_failure() -> None:
    entries = (_entry("One"), _entry("Two"), _entry("Three"))
    deps = SimpleNamespace(active_context=ResolvedActiveContext(entries=entries))

    async def operation(entry: ResolvedContextEntry):
        if entry.display_name == "Two":
            raise IntegrationRateLimitError("Slow down")
        return {"name": entry.display_name}

    results = await run_context_fan_out(deps, binding=_binding(), operation=operation)

    assert [result.status for result in results] == ["success", "error", "success"]
    assert results[1].error_code == "IntegrationRateLimitError"
    assert results[2].data == {"name": "Three"}


async def test_fan_out_write_gate_does_not_call_operation() -> None:
    deps = SimpleNamespace(
        active_context=ResolvedActiveContext(entries=(_entry("Read only", write_allowed=False),))
    )
    calls = 0

    async def operation(_entry: ResolvedContextEntry):
        nonlocal calls
        calls += 1

    results = await run_context_fan_out(
        deps,
        binding=_binding(requires_write=True),
        operation=operation,
    )

    assert calls == 0
    assert results[0].error_code == "write_not_permitted"


async def test_fan_out_write_gate_calls_denial_observer() -> None:
    entry = _entry("Read only", write_allowed=False)
    deps = SimpleNamespace(active_context=ResolvedActiveContext(entries=(entry,)))
    denied_entries = []

    async def on_write_denied(denied_entry: ResolvedContextEntry) -> None:
        denied_entries.append(denied_entry)

    results = await run_context_fan_out(
        deps,
        binding=_binding(requires_write=True),
        operation=lambda _entry: None,
        on_write_denied=on_write_denied,
    )

    assert denied_entries == [entry]
    assert results[0].error_code == "write_not_permitted"


async def test_fan_out_retries_when_no_compatible_entries() -> None:
    deps = SimpleNamespace(active_context=ResolvedActiveContext())

    with pytest.raises(ModelRetry, match="select a context"):
        await run_context_fan_out(deps, binding=_binding(), operation=lambda _entry: None)
