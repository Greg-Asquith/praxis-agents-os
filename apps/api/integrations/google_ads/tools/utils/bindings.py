# apps/api/integrations/google_ads/tools/utils/bindings.py

"""Google Ads active-context bindings and shared result presentation."""

from pydantic_ai import ModelRetry, RunContext

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import IntegrationToolBinding, ToolFieldPresentation
from services.integrations.context.domain import ResolvedContextEntry

GOOGLE_ADS_BINDING = IntegrationToolBinding(
    provider_keys=frozenset({"google_ads"}),
    resource_types=frozenset({"google_ads_account"}),
)
GOOGLE_ADS_WRITE_BINDING = IntegrationToolBinding(
    provider_keys=GOOGLE_ADS_BINDING.provider_keys,
    resource_types=GOOGLE_ADS_BINDING.resource_types,
    requires_write=True,
)
RESULTS_FIELD = (ToolFieldPresentation(key="results", label="Accounts", format="list"),)


def active_google_ads_entries(
    ctx: RunContext[RuntimeDeps],
) -> tuple[ResolvedContextEntry, ...]:
    """Returns the Google Ads entries from Active Context."""
    active_context = ctx.deps.active_context
    entries = (
        active_context.compatible_entries(GOOGLE_ADS_BINDING) if active_context is not None else ()
    )
    if not entries:
        raise ModelRetry(
            "No compatible resources in the active context. "
            "Ask the user to select a context that includes Google Ads."
        )
    return entries
