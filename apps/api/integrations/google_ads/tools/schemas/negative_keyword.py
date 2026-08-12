# apps/api/integrations/google_ads/tools/schemas/negative_keyword.py

"""Typed input contracts shared by Google Ads negative-keyword tools."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NegativeKeywordEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=80)
    match_type: Literal["EXACT", "PHRASE", "BROAD"]

    @field_validator("text", mode="before")
    @classmethod
    def normalize_text_whitespace(cls, value: object) -> object:
        if isinstance(value, str):
            return " ".join(value.split())
        return value


class NegativeKeywordRemovalEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=80)
    match_type: Literal["EXACT", "PHRASE", "BROAD", "ANY"]

    @field_validator("text", mode="before")
    @classmethod
    def normalize_text_whitespace(cls, value: object) -> object:
        if isinstance(value, str):
            return " ".join(value.split())
        return value
