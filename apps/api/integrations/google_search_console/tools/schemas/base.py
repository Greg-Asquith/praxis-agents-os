# apps/api/integrations/google_search_console/tools/schemas/base.py

"""Shared strict contracts for Google Search Console tools."""

from pydantic import BaseModel, ConfigDict


class GoogleSearchConsoleStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
