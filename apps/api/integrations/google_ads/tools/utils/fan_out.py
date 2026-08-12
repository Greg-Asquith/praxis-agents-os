# apps/api/integrations/google_ads/tools/utils/fan_out.py

"""Google Ads fan-out result serialization."""

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic_ai import ToolReturn

from services.integrations.context.results import serialize_fan_out_results


def fan_out_tool_return(items: Sequence[Any]) -> ToolReturn[dict[str, Any]]:
    """Keep complete display rows in the transcript while bounding model results."""
    model_entries: list[dict[str, Any]] = []
    display_entries: list[dict[str, Any]] = []
    for item, serialized in zip(items, serialize_fan_out_results(items), strict=True):
        model_entry = dict(serialized)
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
