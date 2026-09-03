# apps/api/integrations/google_search_console/tools/__init__.py

"""Google Search Console runtime-tool contributions."""

from services.agents.runtime.tools.contract import RuntimeToolDefinition

TOOL_DEFINITIONS: tuple[RuntimeToolDefinition, ...] = ()

__all__ = ["TOOL_DEFINITIONS"]
