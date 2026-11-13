# apps/api/integrations/google_ads/tools/schemas/url_options.py

"""Tracking arguments shared by campaigns, ad groups, keywords, and asset groups."""

from typing import Any

from pydantic import Field, field_validator

from ...operations.url_custom_parameters import validate_url_custom_parameter_items
from .base import GoogleAdsStrictModel

# Google's limit for URL fields.
_MAX_URL = 2_048


class GoogleAdsUrlParameter(GoogleAdsStrictModel):
    key: str = Field(min_length=1, max_length=16)
    value: str = Field(max_length=200)


class GoogleAdsUrlOptions(GoogleAdsStrictModel):
    """Each field set replaces the live value; an empty value or list clears it."""

    final_url_suffix: str | None = Field(default=None, max_length=_MAX_URL)
    tracking_template: str | None = Field(default=None, max_length=_MAX_URL)
    custom_parameters: list[GoogleAdsUrlParameter] | None = Field(default=None, max_length=8)

    @field_validator("final_url_suffix", "tracking_template")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("custom_parameters")
    @classmethod
    def _valid_parameters(
        cls, value: list[GoogleAdsUrlParameter] | None
    ) -> list[GoogleAdsUrlParameter] | None:
        if value is not None:
            validate_url_custom_parameter_items([(item.key, item.value) for item in value])
        return value

    @property
    def requested(self) -> dict[Any, Any]:
        """The URL settings that change, in card terms, with an empty value as null."""
        values: dict[Any, Any] = {}
        if self.final_url_suffix is not None:
            values["final_url_suffix"] = self.final_url_suffix or None
        if self.tracking_template is not None:
            values["tracking_template"] = self.tracking_template or None
        if self.custom_parameters is not None:
            values["custom_parameters"] = [item.model_dump() for item in self.custom_parameters]
        return values
