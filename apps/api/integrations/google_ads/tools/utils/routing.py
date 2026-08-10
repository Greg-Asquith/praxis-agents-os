# apps/api/integrations/google_ads/tools/utils/routing.py

"""Google Ads account routing metadata."""

from pydantic_ai import ModelRetry

from integrations.google_ads.client import normalize_customer_id
from services.integrations.context.domain import ResolvedContextEntry


def login_customer_id(entry: ResolvedContextEntry) -> str:
    value = str(entry.permissions_metadata.get("login_customer_id", "")).strip()
    if not value:
        raise ModelRetry(
            "This Google Ads account is missing routing metadata. Refresh its resources."
        )
    return normalize_customer_id(value)
