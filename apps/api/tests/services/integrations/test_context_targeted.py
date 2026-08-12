"""Tests for scoped entity execution against active integration context."""

from types import SimpleNamespace
from typing import Literal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry

from services.agents.runtime.entity_references.domain import ScopedEntityReference
from services.agents.runtime.tools.contract import IntegrationToolBinding
from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry
from services.integrations.context.targeted import run_context_targets

pytestmark = pytest.mark.asyncio


class _ScopedTestReference(ScopedEntityReference):
    entity_kind: Literal["test_scoped"] = "test_scoped"


def _entry(external_id: str) -> ResolvedContextEntry:
    return ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="gmail",
        resource_type="gmail_mailbox",
        external_id=external_id,
        display_name=external_id,
        connection_id=uuid4(),
        connection_label="Gmail",
        connection_status="active",
        write_allowed=True,
    )


def _reference(entry: ResolvedContextEntry, message_id: str) -> _ScopedTestReference:
    return _ScopedTestReference(
        integration_resource_id=entry.integration_resource_id,
        external_id=message_id,
        label=f"Message {message_id}",
    )


async def test_targets_are_grouped_and_never_fanned_out_to_other_entries() -> None:
    first = _entry("first@example.com")
    second = _entry("second@example.com")
    unused = _entry("unused@example.com")
    operation = AsyncMock(side_effect=lambda entry, refs: [ref.external_id for ref in refs])
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(first, second, unused))),
        tool_name="gmail_read_message",
    )
    binding = IntegrationToolBinding(
        provider_keys=frozenset({"gmail"}),
        resource_types=frozenset({"gmail_mailbox"}),
    )

    results = await run_context_targets(
        ctx,
        binding=binding,
        references=[_reference(first, "m1"), _reference(second, "m2")],
        operation=operation,
    )

    assert [call.args[0].integration_resource_id for call in operation.await_args_list] == [
        first.integration_resource_id,
        second.integration_resource_id,
    ]
    assert [result.data for result in results] == [["m1"], ["m2"]]


async def test_target_missing_from_active_context_fails_closed() -> None:
    active = _entry("active@example.com")
    removed = _entry("removed@example.com")
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(active,))),
        tool_name="gmail_read_message",
    )
    binding = IntegrationToolBinding(
        provider_keys=frozenset({"gmail"}),
        resource_types=frozenset({"gmail_mailbox"}),
    )

    with pytest.raises(ModelRetry, match="no longer in the active integration context"):
        await run_context_targets(
            ctx,
            binding=binding,
            references=[_reference(removed, "m1")],
            operation=AsyncMock(),
        )
