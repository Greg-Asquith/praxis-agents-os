# apps/api/integrations/google_ads/tools/schemas/create_negative_keyword_list.py

"""Result contract for creating negative keyword lists."""

from typing import Literal

from integrations.google_ads.references import GoogleAdsSharedSetReference
from services.integrations.context.results import (
    IntegrationFanOutEntry,
    IntegrationFanOutOutput,
)

from .base import GoogleAdsStrictModel


class GoogleAdsCreateListOutcome(GoogleAdsStrictModel):
    name: str
    outcome: Literal["created", "already_exists", "failed"]
    reference: GoogleAdsSharedSetReference | None = None
    error_code: str | None = None
    message: str | None = None


class GoogleAdsCreateNegativeKeywordListData(GoogleAdsStrictModel):
    outcomes: list[GoogleAdsCreateListOutcome]


class GoogleAdsCreateNegativeKeywordListEntry(IntegrationFanOutEntry):
    data: GoogleAdsCreateNegativeKeywordListData | None = None


class GoogleAdsCreateNegativeKeywordListOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsCreateNegativeKeywordListEntry]
