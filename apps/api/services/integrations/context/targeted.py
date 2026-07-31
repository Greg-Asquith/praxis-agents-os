# apps/api/services/integrations/context/targeted.py

"""Fail-closed execution against explicitly referenced context resources."""

from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from typing import Any
from uuid import UUID

from pydantic_ai import ModelRetry

from core.exceptions.integration import IntegrationError
from services.agents.runtime.entity_references.domain import ScopedEntityReference
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.fan_out import FanOutEntryResult
from services.integrations.context.utils import sanitize_context_error

if False:  # pragma: no cover
    from services.agents.runtime.context import RuntimeDeps
    from services.agents.runtime.tools.contract import IntegrationToolBinding


async def run_context_targets(
    deps: "RuntimeDeps",
    *,
    binding: "IntegrationToolBinding",
    references: Sequence[ScopedEntityReference],
    operation: Callable[[ResolvedContextEntry, Sequence[ScopedEntityReference]], Awaitable[Any]],
    write: bool = False,
    on_write_denied: Callable[[ResolvedContextEntry], Awaitable[None]] | None = None,
) -> list[FanOutEntryResult]:
    """Group references by active-context resource and execute only those scopes."""
    active_context = deps.active_context
    compatible = active_context.compatible_entries(binding) if active_context is not None else ()
    by_resource = {entry.integration_resource_id: entry for entry in compatible}
    grouped: dict[UUID, list[ScopedEntityReference]] = defaultdict(list)
    for reference in references:
        grouped[reference.integration_resource_id].append(reference)

    missing = set(grouped).difference(by_resource)
    if missing:
        raise ModelRetry(
            "One or more selected targets are no longer in the active integration context. "
            "Ask the user to choose the targets again."
        )
    if not grouped:
        raise ModelRetry("No scoped targets were selected.")

    results: list[FanOutEntryResult] = []
    for resource_id, scoped_references in grouped.items():
        entry = by_resource[resource_id]
        base = {
            "integration_resource_id": entry.integration_resource_id,
            "connection_id": entry.connection_id,
            "provider_key": entry.provider_key,
            "external_id": entry.external_id,
            "display_name": entry.display_name,
        }
        if (write or binding.requires_write) and not entry.write_allowed:
            if on_write_denied is not None:
                await on_write_denied(entry)
            results.append(
                FanOutEntryResult(
                    **base,
                    status="error",
                    error_code="write_not_permitted",
                    error_message="This resource does not permit writes.",
                )
            )
            continue
        try:
            data = await operation(entry, tuple(scoped_references))
        except IntegrationError as exc:
            results.append(
                FanOutEntryResult(
                    **base,
                    status="error",
                    error_code=exc.__class__.__name__,
                    error_message=sanitize_context_error(str(exc)),
                )
            )
        except Exception as exc:
            results.append(
                FanOutEntryResult(
                    **base,
                    status="error",
                    error_code=exc.__class__.__name__,
                    error_message=sanitize_context_error(str(exc)),
                )
            )
        else:
            results.append(FanOutEntryResult(**base, status="success", data=data))
    return results
