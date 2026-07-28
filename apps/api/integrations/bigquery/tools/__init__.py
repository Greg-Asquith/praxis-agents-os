# apps/api/integrations/bigquery/tools/__init__.py

"""BigQuery runtime tool contributions."""

from services.agents.runtime.tools.contract import RuntimeToolDefinition

TOOL_DEFINITIONS: tuple[RuntimeToolDefinition, ...] = ()

__all__ = ["TOOL_DEFINITIONS"]
