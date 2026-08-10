# apps/api/integrations/google_ads/tools/utils/fan_out.py

"""Google Ads fan-out result serialization."""

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic_ai import ToolReturn


def fan_out_dict(item) -> dict[str, Any]:
    return {
        "integration_resource_id": item.integration_resource_id,
        "connection_id": item.connection_id,
        "provider_key": item.provider_key,
        "external_id": item.external_id,
        "display_name": item.display_name,
        "status": item.status,
        "data": item.data,
        "error_code": item.error_code,
        "error_message": item.error_message,
    }


def fan_out_tool_return(items: Sequence[Any]) -> ToolReturn[dict[str, Any]]:
    """Keep complete display rows in the transcript while bounding model results."""
    model_entries: list[dict[str, Any]] = []
    display_entries: list[dict[str, Any]] = []
    for item in items:
        model_entry = fan_out_dict(item)
        display_entry = dict(model_entry)
        if isinstance(item.data, Mapping):
            model_entry["data"] = item.data.get("model_result")
            display_entry["data"] = item.data.get("display_result")
        model_entries.append(model_entry)
        display_entries.append(display_entry)
    return ToolReturn(
        return_value={"results": model_entries},
        metadata={"public_result": {"results": display_entries}},
    )
