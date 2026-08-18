# apps/api/integrations/google_analytics/tools/utils/bindings.py

"""Google Analytics active-context binding and result presentation."""

from services.agents.runtime.tools.contract import IntegrationToolBinding, ToolFieldPresentation

GOOGLE_ANALYTICS_BINDING = IntegrationToolBinding(
    provider_keys=frozenset({"google_analytics"}),
    resource_types=frozenset({"google_analytics_property"}),
)
RESULTS_FIELD = (ToolFieldPresentation(key="results", label="Properties", format="list"),)
