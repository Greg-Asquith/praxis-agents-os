# apps/api/integrations/google_ads/tools/schemas/recommendations.py

"""Input and result contracts for Google Ads recommendation actions."""

from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from integrations.google_ads.recommendation_utils import (
    ad_group_customer_id,
    recommendation_customer_id,
)
from services.integrations.context.results import (
    IntegrationFanOutEntry,
    IntegrationFanOutOutput,
)

from .base import GoogleAdsStrictModel

_MAX_INT64 = (1 << 63) - 1


class _RecommendationParameterBase(GoogleAdsStrictModel):
    recommendation_resource_name: str = Field(min_length=1, max_length=320)

    @field_validator("recommendation_resource_name")
    @classmethod
    def validate_recommendation_resource_name(cls, value: str) -> str:
        if recommendation_customer_id(value) is None:
            raise ValueError("Recommendation resource name is invalid")
        return value


class GoogleAdsCampaignBudgetParameters(_RecommendationParameterBase):
    parameter_type: Literal["campaignBudget"] = "campaignBudget"
    new_budget_amount_micros: int = Field(gt=0, le=_MAX_INT64)


class GoogleAdsKeywordParameters(_RecommendationParameterBase):
    parameter_type: Literal["keyword"] = "keyword"
    ad_group: str = Field(
        min_length=1,
        max_length=320,
        pattern=r"^customers/\d{1,32}/adGroups/\d{1,32}$",
    )
    match_type: Literal["EXACT", "PHRASE", "BROAD"]
    cpc_bid_micros: int | None = Field(default=None, gt=0, le=_MAX_INT64)

    @model_validator(mode="after")
    def validate_ad_group_scope(self) -> "GoogleAdsKeywordParameters":
        if ad_group_customer_id(self.ad_group) != recommendation_customer_id(
            self.recommendation_resource_name
        ):
            raise ValueError("Keyword ad group must belong to the recommendation customer")
        return self


class GoogleAdsTargetCpaOptInParameters(_RecommendationParameterBase):
    parameter_type: Literal["targetCpaOptIn"] = "targetCpaOptIn"
    target_cpa_micros: int = Field(gt=0, le=_MAX_INT64)
    new_campaign_budget_amount_micros: int | None = Field(
        default=None,
        gt=0,
        le=_MAX_INT64,
    )


class GoogleAdsTargetRoasOptInParameters(_RecommendationParameterBase):
    parameter_type: Literal["targetRoasOptIn"] = "targetRoasOptIn"
    target_roas: float | None = Field(default=None, ge=0.01, le=1000.0)
    new_campaign_budget_amount_micros: int | None = Field(
        default=None,
        gt=0,
        le=_MAX_INT64,
    )

    @model_validator(mode="after")
    def require_value(self) -> "GoogleAdsTargetRoasOptInParameters":
        if self.target_roas is None and self.new_campaign_budget_amount_micros is None:
            raise ValueError("Target ROAS opt-in parameters require a target or budget")
        return self


class GoogleAdsMoveUnusedBudgetParameters(_RecommendationParameterBase):
    parameter_type: Literal["moveUnusedBudget"] = "moveUnusedBudget"
    budget_micros_to_move: int = Field(gt=0, le=_MAX_INT64)


class GoogleAdsUseBroadMatchKeywordParameters(_RecommendationParameterBase):
    parameter_type: Literal["useBroadMatchKeyword"] = "useBroadMatchKeyword"
    new_budget_amount_micros: int = Field(gt=0, le=_MAX_INT64)


class GoogleAdsRaiseTargetCpaBidTooLowParameters(_RecommendationParameterBase):
    parameter_type: Literal["raiseTargetCpaBidTooLow"] = "raiseTargetCpaBidTooLow"
    target_multiplier: float = Field(gt=1.0, allow_inf_nan=False)


class GoogleAdsForecastingSetTargetRoasParameters(_RecommendationParameterBase):
    parameter_type: Literal["forecastingSetTargetRoas"] = "forecastingSetTargetRoas"
    target_roas: float | None = Field(default=None, ge=0.01, le=1000.0)
    campaign_budget_amount_micros: int | None = Field(default=None, gt=0, le=_MAX_INT64)

    @model_validator(mode="after")
    def require_value(self) -> "GoogleAdsForecastingSetTargetRoasParameters":
        if self.target_roas is None and self.campaign_budget_amount_micros is None:
            raise ValueError("Forecasting target ROAS parameters require a target or budget")
        return self


class GoogleAdsRaiseTargetCpaParameters(_RecommendationParameterBase):
    parameter_type: Literal["raiseTargetCpa"] = "raiseTargetCpa"
    target_cpa_multiplier: float = Field(gt=0, allow_inf_nan=False)


class GoogleAdsLowerTargetRoasParameters(_RecommendationParameterBase):
    parameter_type: Literal["lowerTargetRoas"] = "lowerTargetRoas"
    target_roas_multiplier: float = Field(gt=0, allow_inf_nan=False)


class GoogleAdsForecastingSetTargetCpaParameters(_RecommendationParameterBase):
    parameter_type: Literal["forecastingSetTargetCpa"] = "forecastingSetTargetCpa"
    target_cpa_micros: int | None = Field(default=None, gt=0, le=_MAX_INT64)
    campaign_budget_amount_micros: int | None = Field(default=None, gt=0, le=_MAX_INT64)

    @model_validator(mode="after")
    def require_value(self) -> "GoogleAdsForecastingSetTargetCpaParameters":
        if self.target_cpa_micros is None and self.campaign_budget_amount_micros is None:
            raise ValueError("Forecasting target CPA parameters require a target or budget")
        return self


class GoogleAdsSetTargetCpaParameters(_RecommendationParameterBase):
    parameter_type: Literal["setTargetCpa"] = "setTargetCpa"
    target_cpa_micros: int | None = Field(default=None, gt=0, le=_MAX_INT64)
    campaign_budget_amount_micros: int | None = Field(default=None, gt=0, le=_MAX_INT64)

    @model_validator(mode="after")
    def require_value(self) -> "GoogleAdsSetTargetCpaParameters":
        if self.target_cpa_micros is None and self.campaign_budget_amount_micros is None:
            raise ValueError("Target CPA parameters require a target or budget")
        return self


class GoogleAdsSetTargetRoasParameters(_RecommendationParameterBase):
    parameter_type: Literal["setTargetRoas"] = "setTargetRoas"
    target_roas: float | None = Field(default=None, ge=0.01, le=1000.0)
    campaign_budget_amount_micros: int | None = Field(default=None, gt=0, le=_MAX_INT64)

    @model_validator(mode="after")
    def require_value(self) -> "GoogleAdsSetTargetRoasParameters":
        if self.target_roas is None and self.campaign_budget_amount_micros is None:
            raise ValueError("Target ROAS parameters require a target or budget")
        return self


GoogleAdsRecommendationApplyParameters = Annotated[
    GoogleAdsCampaignBudgetParameters
    | GoogleAdsKeywordParameters
    | GoogleAdsTargetCpaOptInParameters
    | GoogleAdsTargetRoasOptInParameters
    | GoogleAdsMoveUnusedBudgetParameters
    | GoogleAdsUseBroadMatchKeywordParameters
    | GoogleAdsRaiseTargetCpaBidTooLowParameters
    | GoogleAdsForecastingSetTargetRoasParameters
    | GoogleAdsRaiseTargetCpaParameters
    | GoogleAdsLowerTargetRoasParameters
    | GoogleAdsForecastingSetTargetCpaParameters
    | GoogleAdsSetTargetCpaParameters
    | GoogleAdsSetTargetRoasParameters,
    Field(discriminator="parameter_type"),
]


class GoogleAdsRecommendationMetrics(GoogleAdsStrictModel):
    impressions: float | None = None
    clicks: float | None = None
    cost_micros: int | None = None
    conversions: float | None = None
    conversions_value: float | None = None
    video_views: float | None = None


class GoogleAdsRecommendationImpact(GoogleAdsStrictModel):
    base_metrics: GoogleAdsRecommendationMetrics | None = None
    potential_metrics: GoogleAdsRecommendationMetrics | None = None


class GoogleAdsApplyRecommendationOutcome(GoogleAdsStrictModel):
    recommendation_resource_name: str
    recommendation_type: str
    recommendation_label: str
    affected_campaigns: list[str]
    requested_parameters: GoogleAdsRecommendationApplyParameters | None = None
    impact: GoogleAdsRecommendationImpact | None = None
    outcome: Literal["applied", "failed", "unverified"]
    external_ref: str | None = None
    message: str | None = None
    error_code: str | None = None


class GoogleAdsApplyRecommendationsData(GoogleAdsStrictModel):
    recommendations: list[GoogleAdsApplyRecommendationOutcome]


class GoogleAdsApplyRecommendationsEntry(IntegrationFanOutEntry):
    data: GoogleAdsApplyRecommendationsData | None = None


class GoogleAdsApplyRecommendationsOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsApplyRecommendationsEntry]


class GoogleAdsDismissRecommendationOutcome(GoogleAdsStrictModel):
    recommendation_resource_name: str
    recommendation_type: str
    recommendation_label: str
    affected_campaigns: list[str]
    outcome: Literal["dismissed", "already_dismissed", "failed", "unverified"]
    external_ref: str | None = None
    message: str | None = None
    error_code: str | None = None


class GoogleAdsDismissRecommendationsData(GoogleAdsStrictModel):
    recommendations: list[GoogleAdsDismissRecommendationOutcome]


class GoogleAdsDismissRecommendationsEntry(IntegrationFanOutEntry):
    data: GoogleAdsDismissRecommendationsData | None = None


class GoogleAdsDismissRecommendationsOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsDismissRecommendationsEntry]
