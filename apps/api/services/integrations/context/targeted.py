# apps/api/services/integrations/context/targeted.py

"""Fail-closed execution against explicitly referenced context resources."""

from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Any

from pydantic_ai import ModelRetry

from services.agents.runtime.entity_references.domain import ScopedEntityReference
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.execution import _run_authorized_entries
from services.integrations.context.results import IntegrationContextResult

if TYPE_CHECKING:
    from pydantic_ai import RunContext

    from services.agents.runtime.context import RuntimeDeps
    from services.agents.runtime.tools.contract import IntegrationToolBinding


async def run_context_targets(
    ctx: "RunContext[RuntimeDeps]",
    *,
    binding: "IntegrationToolBinding",
    references: Sequence[ScopedEntityReference],
    operation: Callable[[ResolvedContextEntry, Sequence[ScopedEntityReference]], Awaitable[Any]],
) -> list[IntegrationContextResult]:
    """Group references by active-context resource and execute only those scopes."""
    active_context = ctx.deps.active_context
    compatible = active_context.compatible_entries(binding) if active_context is not None else ()
    entries_by_scope: dict[str, list[ResolvedContextEntry]] = defaultdict(list)
    for entry in compatible:
        entries_by_scope[entry.external_id].append(entry)

    grouped: dict[str, list[ScopedEntityReference]] = defaultdict(list)
    for reference in references:
        grouped[reference.provider_scope_id].append(reference)

    # Ambiguous duplicate scopes fail closed like missing ones instead of last-write-wins.
    missing = {scope for scope in grouped if len(entries_by_scope.get(scope, ())) != 1}
    if missing:
        raise ModelRetry(
            "One or more selected targets are no longer in the active integration context. "
            "Ask the user to choose the targets again."
        )
    if not grouped:
        raise ModelRetry("No scoped targets were selected.")

    return await _run_authorized_entries(
        ctx,
        binding=binding,
        selected=tuple(
            (entries_by_scope[scope][0], tuple(scoped_references))
            for scope, scoped_references in grouped.items()
        ),
        operation=operation,
    )
