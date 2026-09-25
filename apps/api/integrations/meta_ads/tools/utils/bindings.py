# apps/api/integrations/meta_ads/tools/utils/bindings.py

"""Meta Ads ad account bindings and shared result presentation."""

from services.agents.runtime.tools.contract import IntegrationToolBinding, ToolFieldPresentation

META_ADS_BINDING = IntegrationToolBinding(
    provider_keys=frozenset({"meta_ads"}),
    resource_types=frozenset({"meta_ads_ad_account"}),
)
META_ADS_WRITE_BINDING = IntegrationToolBinding(
    provider_keys=META_ADS_BINDING.provider_keys,
    resource_types=META_ADS_BINDING.resource_types,
    requires_write=True,
)
RESULTS_FIELD = (ToolFieldPresentation(key="results", label="Ad accounts", format="list"),)
