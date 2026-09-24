# apps/api/integrations/meta_ads/tools/utils/bindings.py

"""Ad account bindings for Meta Ads."""

from services.agents.runtime.tools.contract import IntegrationToolBinding

META_ADS_BINDING = IntegrationToolBinding(
    provider_keys=frozenset({"meta_ads"}),
    resource_types=frozenset({"meta_ads_ad_account"}),
)
META_ADS_WRITE_BINDING = IntegrationToolBinding(
    provider_keys=META_ADS_BINDING.provider_keys,
    resource_types=META_ADS_BINDING.resource_types,
    requires_write=True,
)
