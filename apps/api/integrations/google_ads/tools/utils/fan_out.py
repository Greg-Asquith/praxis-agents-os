# apps/api/integrations/google_ads/tools/utils/fan_out.py

"""Google Ads fan-out result serialization."""

from typing import Any


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
