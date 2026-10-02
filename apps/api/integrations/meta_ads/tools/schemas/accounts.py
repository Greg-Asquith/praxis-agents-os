# apps/api/integrations/meta_ads/tools/schemas/accounts.py

"""Typed Meta ad account overviews with exact currency amounts."""

from pydantic import Field

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...models import MetaAdsMoney, MetaAdsStrictModel, MetaAdsText


class MetaAdsAccountData(MetaAdsStrictModel):
    name: MetaAdsText | None
    status: MetaAdsText
    disable_reason: MetaAdsText | None
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    timezone_name: MetaAdsText | None
    amount_spent: MetaAdsMoney | None
    spend_cap: MetaAdsMoney | None
    spend_cap_remaining: MetaAdsMoney | None
    balance: MetaAdsMoney | None
    min_daily_budget: MetaAdsMoney | None


class MetaAdsAccountEntry(IntegrationFanOutEntry):
    data: MetaAdsAccountData | None = None


class MetaAdsAccountsOutput(IntegrationFanOutOutput):
    results: list[MetaAdsAccountEntry]
