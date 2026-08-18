# apps/api/services/classifiers/schemas.py

"""Pydantic contracts for workspace classifier routes."""

import re
from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.settings import settings
from models.classifiers import Classifier
from services.agents.models.domain import ModelConfigurationError
from services.agents.models.registry import get_model
from services.agents.runtime.tools.native.classifier import (
    CLASSIFIER_MAX_INSTRUCTIONS_CHARS,
    SUPPORTED_CLASSIFIER_PROVIDERS,
)
from utils.pagination import OffsetPage
from utils.validation import normalize_optional_text

CLASSIFIER_NAME_PATTERN = r"^[a-z][a-z0-9_]*$"
CLASSIFIER_NAME_MAX_CHARS = 48
CLASSIFIER_DISPLAY_NAME_MAX_CHARS = 100
CLASSIFIER_DESCRIPTION_MAX_CHARS = 1_024
CLASSIFIER_LABEL_MAX_CHARS = 64
CLASSIFIER_LABEL_DESCRIPTION_MAX_CHARS = 256
_CLASSIFIER_NAME_RE = re.compile(CLASSIFIER_NAME_PATTERN)


class ClassifierLabel(BaseModel):
    label: str = Field(min_length=1, max_length=CLASSIFIER_LABEL_MAX_CHARS)
    description: str | None = Field(default=None, max_length=CLASSIFIER_LABEL_DESCRIPTION_MAX_CHARS)

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        return normalize_optional_text(value)


class ClassifierRead(BaseModel):
    id: UUID
    workspace_id: UUID
    name: str
    display_name: str
    description: str
    instructions: str | None = None
    labels: list[ClassifierLabel]
    model_provider: str | None = None
    model: str | None = None
    is_active: bool
    created_by: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_classifier(cls, classifier: Classifier) -> "ClassifierRead":
        return cls.model_validate(classifier)


class ClassifiersListResponse(OffsetPage):
    classifiers: list[ClassifierRead]


class _ClassifierWriteBase(BaseModel):
    @field_validator("name", check_fields=False)
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not _CLASSIFIER_NAME_RE.fullmatch(normalized):
            raise ValueError(f"name must match snake_case pattern {CLASSIFIER_NAME_PATTERN}")
        return normalized

    @field_validator("display_name", "description", check_fields=False)
    @classmethod
    def normalize_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    @field_validator("instructions", check_fields=False)
    @classmethod
    def normalize_instructions(cls, value: str | None) -> str | None:
        return normalize_optional_text(value)

    @field_validator("model_provider", check_fields=False)
    @classmethod
    def normalize_provider(cls, value: str | None) -> str | None:
        normalized = normalize_optional_text(value)
        return normalized.lower() if normalized is not None else None

    @field_validator("model", check_fields=False)
    @classmethod
    def normalize_model(cls, value: str | None) -> str | None:
        return normalize_optional_text(value)

    @field_validator("labels", check_fields=False)
    @classmethod
    def validate_unique_labels(
        cls, value: list[ClassifierLabel] | None
    ) -> list[ClassifierLabel] | None:
        if value is None:
            return None
        labels = [entry.label for entry in value]
        if len(labels) != len(set(labels)):
            raise ValueError("labels must be unique after whitespace normalization")
        return value

    @model_validator(mode="after")
    def validate_model_pair(self) -> Self:
        provider_set = self.model_provider is not None
        model_set = self.model is not None
        if provider_set != model_set:
            raise ValueError("model_provider and model must be supplied together")
        if not provider_set:
            return self
        provider = self.model_provider
        model = self.model
        if provider is None or model is None:
            raise ValueError("model_provider and model must be supplied together")
        if provider not in SUPPORTED_CLASSIFIER_PROVIDERS:
            raise ValueError("model_provider must be openai, anthropic, or google")
        try:
            info = get_model(provider, model)
        except ModelConfigurationError as exc:
            raise ValueError("model must be a known catalog entry for model_provider") from exc
        if info.deprecated:
            raise ValueError("deprecated models cannot be selected")
        if not info.supports_structured_output:
            raise ValueError("model must support structured output")
        return self


class ClassifierCreateRequest(_ClassifierWriteBase):
    name: str = Field(min_length=1, max_length=CLASSIFIER_NAME_MAX_CHARS)
    display_name: str = Field(min_length=1, max_length=CLASSIFIER_DISPLAY_NAME_MAX_CHARS)
    description: str = Field(min_length=1, max_length=CLASSIFIER_DESCRIPTION_MAX_CHARS)
    instructions: str | None = Field(default=None, max_length=CLASSIFIER_MAX_INSTRUCTIONS_CHARS)
    labels: list[ClassifierLabel] = Field(
        min_length=2,
        max_length=settings.NATIVE_CLASSIFIER_MAX_LABELS,
    )
    model_provider: str | None = Field(default=None, max_length=50)
    model: str | None = Field(default=None, max_length=100)
    is_active: bool = True


class ClassifierUpdateRequest(_ClassifierWriteBase):
    name: str | None = Field(default=None, min_length=1, max_length=CLASSIFIER_NAME_MAX_CHARS)
    display_name: str | None = Field(
        default=None, min_length=1, max_length=CLASSIFIER_DISPLAY_NAME_MAX_CHARS
    )
    description: str | None = Field(
        default=None, min_length=1, max_length=CLASSIFIER_DESCRIPTION_MAX_CHARS
    )
    instructions: str | None = Field(default=None, max_length=CLASSIFIER_MAX_INSTRUCTIONS_CHARS)
    labels: list[ClassifierLabel] | None = Field(
        default=None,
        min_length=2,
        max_length=settings.NATIVE_CLASSIFIER_MAX_LABELS,
    )
    model_provider: str | None = Field(default=None, max_length=50)
    model: str | None = Field(default=None, max_length=100)
    is_active: bool | None = None

    @model_validator(mode="after")
    def validate_model_pair_update(self) -> Self:
        model_fields = {"model_provider", "model"}
        supplied_model_fields = model_fields.intersection(self.model_fields_set)
        if supplied_model_fields and supplied_model_fields != model_fields:
            raise ValueError("model_provider and model must be supplied together")
        return self
