# apps/api/integrations/meta_ads/operations/get_account.py

"""Read an ad account's current status and monetary totals."""

from decimal import Decimal, localcontext

from services.integrations.http import IntegrationRequestPolicy

from ..client import MetaAdsClient, ad_account_path
from ..throttle import ensure_account_available
from ..tools.schemas.accounts import MetaAdsAccountData
from .values import account_status, bounded_string, disable_reason, money_value, require_currency

_OPERATION = "get_account"
_FIELDS = "name,account_status,disable_reason,currency,timezone_name,amount_spent,spend_cap,balance,min_daily_budget"


async def get_account(
    client: MetaAdsClient, *, account_id: str, max_response_bytes: int | None = None
) -> MetaAdsAccountData:
    ensure_account_available(account_id, operation=_OPERATION)
    raw = await client.graph_get(
        ad_account_path(account_id),
        params={"fields": _FIELDS},
        operation=_OPERATION,
        policy=IntegrationRequestPolicy.READ,
        max_response_bytes=max_response_bytes,
    )
    currency = require_currency(raw.get("currency"), operation=_OPERATION)
    amounts = {
        field: money_value(raw.get(field), currency, operation=_OPERATION)
        for field in ("amount_spent", "spend_cap", "balance", "min_daily_budget")
    }
    cap = amounts["spend_cap"]
    if cap is not None and Decimal(cap) == 0:
        amounts["spend_cap"] = cap = None
    remaining = None
    if cap is not None and amounts["amount_spent"] is not None:
        with localcontext() as context:
            context.prec = 520
            remaining = format(Decimal(cap) - Decimal(amounts["amount_spent"]), "f")
    return MetaAdsAccountData(
        name=bounded_string(raw.get("name"), operation=_OPERATION),
        status=account_status(raw.get("account_status")),
        disable_reason=disable_reason(raw.get("disable_reason")),
        currency=currency,
        timezone_name=bounded_string(raw.get("timezone_name"), operation=_OPERATION),
        spend_cap_remaining=remaining,
        **amounts,
    )
