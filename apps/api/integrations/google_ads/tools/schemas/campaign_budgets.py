# apps/api/integrations/google_ads/tools/schemas/campaign_budgets.py

"""The amount type for Google Ads campaign budgets."""

from typing import Annotated

from pydantic import AfterValidator, Field

from ..utils.money import money_to_micros


def _valid_money_amount(value: str) -> str:
    money_to_micros(value, label="budget amount")
    return value


GoogleAdsMoneyAmount = Annotated[
    str,
    Field(
        min_length=1,
        max_length=32,
        description=(
            "Positive decimal amount in the Google Ads account currency, with up to six "
            "decimal places. Use currency units, not micros."
        ),
    ),
    AfterValidator(_valid_money_amount),
]
