# apps/api/services/integrations/context/fan_out.py

"""Sequential execution across compatible active-context resources."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from pydantic_ai import ModelRetry

from core.exceptions.integration import IntegrationError
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.utils import sanitize_context_error
from services.integrations.manifest import PROVIDER_MANIFESTS

if TYPE_CHECKING:
    from services.agents.runtime.context import RuntimeDeps
    from services.agents.runtime.tools.contract import IntegrationToolBinding


@dataclass(frozen=True)
class FanOutEntryResult:
    integration_resource_id: UUID
    connection_id: UUID
    provider_key: str
    external_id: str
    display_name: str
    status: Literal["success", "error"]
    data: Any | None = None
    error_code: str | None = None
    error_message: str | None = None


async def run_context_fan_out(
    deps: "RuntimeDeps",
    *,
    binding: "IntegrationToolBinding",
    operation: Callable[[ResolvedContextEntry], Awaitable[Any]],
    write: bool = False,
    on_write_denied: Callable[[ResolvedContextEntry], Awaitable[None]] | None = None,
) -> list[FanOutEntryResult]:
    """Run an operation once per compatible entry and isolate failures."""
    active_context = deps.active_context
    entries = active_context.compatible_entries(binding) if active_context is not None else ()
    if not entries:
        providers = ", ".join(
            sorted(
                PROVIDER_MANIFESTS[key].display_name if key in PROVIDER_MANIFESTS else key
                for key in binding.provider_keys
            )
        )
        raise ModelRetry(
            "No compatible resources in the active context. "
            f"Ask the user to select a context that includes {providers}."
        )

    results: list[FanOutEntryResult] = []
    for entry in entries:
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
            data = await operation(entry)
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
