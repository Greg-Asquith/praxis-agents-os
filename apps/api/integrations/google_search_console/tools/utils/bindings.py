# apps/api/integrations/google_search_console/tools/utils/bindings.py

"""Google Search Console active-context binding and result presentation."""

from services.agents.runtime.tools.contract import IntegrationToolBinding, ToolFieldPresentation

GOOGLE_SEARCH_CONSOLE_BINDING = IntegrationToolBinding(
    provider_keys=frozenset({"google_search_console"}),
    resource_types=frozenset({"google_search_console_site"}),
)
GOOGLE_SEARCH_CONSOLE_WRITE_BINDING = IntegrationToolBinding(
    provider_keys=frozenset({"google_search_console"}),
    resource_types=frozenset({"google_search_console_site"}),
    requires_write=True,
)
RESULTS_FIELD = (ToolFieldPresentation(key="results", label="Sites", format="list"),)
