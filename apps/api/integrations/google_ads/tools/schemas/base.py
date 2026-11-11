# apps/api/integrations/google_ads/tools/schemas/base.py

"""Shared strict base for Google Ads result contracts."""

from pydantic import AfterValidator, BaseModel, ConfigDict

from ..utils.money import money_to_micros


class GoogleAdsStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def money_validator(label: str) -> AfterValidator:
    """Checks a positive decimal amount in the account currency, naming `label` in the error."""

    def check(value: str) -> str:
        money_to_micros(value, label=label)
        return value.strip()

    return AfterValidator(check)
