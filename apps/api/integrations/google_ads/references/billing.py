# apps/api/integrations/google_ads/references/billing.py

from typing import ClassVar, Literal

from pydantic import Field

from services.integrations.entity_references import ScopedEntityReference

_CUSTOMER_ID = Field(
    min_length=1,
    max_length=32,
    pattern=r"^\d+$",
    description="Google Ads customer ID, normalized to digits without hyphens.",
)


class GoogleAdsBillingSetupReference(ScopedEntityReference):
    """One billing setup, the link between an account and the payments account that pays."""

    entity_kind: Literal["google_ads_billing_setup"] = "google_ads_billing_setup"
    customer_id: str = _CUSTOMER_ID
    billing_setup_id: str = Field(min_length=1, max_length=32, pattern=r"^\d+$")
    identity_fields: ClassVar[tuple[str, ...]] = (
        *ScopedEntityReference.identity_fields,
        "customer_id",
        "billing_setup_id",
    )

    @property
    def provider_scope_id(self) -> str:
        return self.customer_id

    @property
    def provider_entity_id(self) -> str:
        return self.billing_setup_id

    @property
    def resource_name(self) -> str:
        return f"customers/{self.customer_id}/billingSetups/{self.billing_setup_id}"


class GoogleAdsAccountBudgetReference(ScopedEntityReference):
    """One account spending limit, Google's `accountBudgets` resource."""

    entity_kind: Literal["google_ads_account_budget"] = "google_ads_account_budget"
    customer_id: str = _CUSTOMER_ID
    account_budget_id: str = Field(min_length=1, max_length=32, pattern=r"^\d+$")
    identity_fields: ClassVar[tuple[str, ...]] = (
        *ScopedEntityReference.identity_fields,
        "customer_id",
        "account_budget_id",
    )

    @property
    def provider_scope_id(self) -> str:
        return self.customer_id

    @property
    def provider_entity_id(self) -> str:
        return self.account_budget_id

    @property
    def resource_name(self) -> str:
        return f"customers/{self.customer_id}/accountBudgets/{self.account_budget_id}"
