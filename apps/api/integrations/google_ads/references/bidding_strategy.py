# apps/api/integrations/google_ads/references/bidding_strategy.py

from typing import Any, ClassVar, Literal

from pydantic import Field, field_validator

from services.integrations.entity_references import ScopedEntityReference


class GoogleAdsBiddingStrategyReference(ScopedEntityReference):
    """One portfolio bidding strategy that campaigns in its account can share."""

    entity_kind: Literal["google_ads_bidding_strategy"] = "google_ads_bidding_strategy"
    customer_id: str = Field(
        min_length=1,
        max_length=32,
        pattern=r"^\d+$",
        description="Google Ads customer ID, normalized to digits without hyphens.",
    )
    bidding_strategy_id: str = Field(min_length=1, max_length=32, pattern=r"^\d+$")
    # Google's strategy type, such as `TARGET_CPA` or `MAXIMIZE_CONVERSION_VALUE`.
    strategy_type: str | None = Field(default=None, max_length=64)
    campaign_count: int | None = Field(default=None, ge=0)
    identity_fields: ClassVar[tuple[str, ...]] = (
        *ScopedEntityReference.identity_fields,
        "customer_id",
        "bidding_strategy_id",
    )

    @field_validator("customer_id", mode="before")
    @classmethod
    def normalize_customer_id(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().replace("-", "")
        return value

    @property
    def provider_scope_id(self) -> str:
        return self.customer_id

    @property
    def provider_entity_id(self) -> str:
        return self.bidding_strategy_id

    @property
    def resource_name(self) -> str:
        return f"customers/{self.customer_id}/biddingStrategies/{self.bidding_strategy_id}"
