# apps/api/integrations/google_analytics/tools/schemas/base.py

"""Shared strict base and scalar values for Google Analytics tools."""

from pydantic import BaseModel, ConfigDict

type GoogleAnalyticsValue = str | int | float | None


class GoogleAnalyticsStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
