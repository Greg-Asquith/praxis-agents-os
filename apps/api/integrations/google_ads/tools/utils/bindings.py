# apps/api/integrations/google_ads/tools/utils/bindings.py

"""Google Ads active-context bindings and shared result presentation."""

from services.agents.runtime.tools.contract import IntegrationToolBinding, ToolFieldPresentation

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
