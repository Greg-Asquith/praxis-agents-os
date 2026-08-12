# apps/api/services/integrations/context/fan_out.py

"""Sequential execution across compatible active-context resources."""

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from pydantic_ai import ModelRetry

from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.execution import _run_authorized_entries
from services.integrations.context.results import IntegrationFanOutEntry
from services.integrations.context.schemas import MAX_ACTIVE_CONTEXT_TARGETS
from services.integrations.manifest import PROVIDER_MANIFESTS

if TYPE_CHECKING:
    from pydantic_ai import RunContext

    from services.agents.runtime.context import RuntimeDeps
    from services.agents.runtime.tools.contract import IntegrationToolBinding


async def run_context_fan_out(
    ctx: "RunContext[RuntimeDeps]",
    *,
    binding: "IntegrationToolBinding",
    operation: Callable[[ResolvedContextEntry], Awaitable[Any]],
) -> list[IntegrationFanOutEntry]:
    """Run an operation once per compatible entry and isolate failures."""
    active_context = ctx.deps.active_context
    entries = (
        active_context.compatible_entries(binding)[:MAX_ACTIVE_CONTEXT_TARGETS]
        if active_context is not None
        else ()
    )
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

    async def execute(entry: ResolvedContextEntry, _operation_input: None) -> Any:
        return await operation(entry)

    return await _run_authorized_entries(
        ctx,
        binding=binding,
        selected=tuple((entry, None) for entry in entries),
        operation=execute,
    )
