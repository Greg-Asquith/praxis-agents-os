# apps/api/services/integrations/context/execution.py

"""Shared authorization and failure isolation for context operations."""

from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Any

from core.exceptions.integration import IntegrationFailureDisposition
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.results import IntegrationFanOutEntry
from services.integrations.context.utils import sanitize_context_error

if TYPE_CHECKING:
    from pydantic_ai import RunContext

    from services.agents.runtime.context import RuntimeDeps
    from services.agents.runtime.tools.contract import IntegrationToolBinding


async def _run_authorized_entries[T](
    ctx: "RunContext[RuntimeDeps]",
    *,
    binding: "IntegrationToolBinding",
    selected: Sequence[tuple[ResolvedContextEntry, T]],
    operation: Callable[[ResolvedContextEntry, T], Awaitable[Any]],
) -> list[IntegrationFanOutEntry]:
    """Execute selected entries with one authorization and isolation loop."""
    from services.integrations.operations import _resolve_dispatched_integration_definition

    definition = _resolve_dispatched_integration_definition(ctx)
    if definition.integration_binding != binding:
        raise RuntimeError("Context binding does not match the dispatched integration tool")

    results: list[IntegrationFanOutEntry] = []
    for entry, operation_input in selected:
        base = {
            "integration_resource_id": entry.integration_resource_id,
            "connection_id": entry.connection_id,
            "provider_key": entry.provider_key,
            "external_id": entry.external_id,
            "display_name": entry.display_name,
        }
        if binding.requires_write and not entry.write_allowed:
            from services.integrations.operations import record_integration_write_denial

            await record_integration_write_denial(ctx, entry)
            results.append(
                IntegrationFanOutEntry(
                    **base,
                    status="error",
                    error_code="write_not_permitted",
                    error_message="This resource does not permit writes.",
                )
            )
            continue
        try:
            data = await operation(entry, operation_input)
        except Exception as exc:
            error_code = (
                "unverified_mutation"
                if getattr(exc, "failure_disposition", None)
                is IntegrationFailureDisposition.AMBIGUOUS
                else exc.__class__.__name__
            )
            results.append(
                IntegrationFanOutEntry(
                    **base,
                    status="error",
                    error_code=error_code,
                    error_message=sanitize_context_error(str(exc)),
                )
            )
        else:
            results.append(IntegrationFanOutEntry(**base, status="success", data=data))
    return results
