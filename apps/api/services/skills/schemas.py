# apps/api/services/skills/schemas.py

"""Pydantic contracts for workspace skill routes."""

import re
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.skills import Skill
from utils.validation import normalize_optional_text

SKILL_NAME_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
_SKILL_NAME_RE = re.compile(SKILL_NAME_PATTERN)


class SkillRead(BaseModel):
    id: UUID
    name: str
    human_name: str | None = None
    description: str
    instructions: str
    workspace_id: UUID
    created_by: UUID
    documentation_refs: dict[str, Any] = Field(default_factory=dict)
    is_active: bool
    is_favorite: bool
    last_used_at: datetime | None = None
    metadata_json: dict[str, Any] | None = Field(default=None, serialization_alias="metadata")
    created_at: datetime
    updated_at: datetime
    deleted: bool
    deleted_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @classmethod
    def from_skill(cls, skill: Skill) -> "SkillRead":
        return cls.model_validate(skill)


class SkillsListResponse(BaseModel):
    skills: list[SkillRead]
    total: int
    limit: int
    offset: int


class SkillCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    human_name: str | None = Field(default=None, max_length=255)
    description: str = Field(min_length=1, max_length=1024)
    instructions: str = Field(min_length=1, max_length=20000)
    is_active: bool = True
    is_favorite: bool = False
    metadata_json: dict[str, Any] | None = Field(default=None, alias="metadata")

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        if not _SKILL_NAME_RE.fullmatch(normalized):
            raise ValueError(
                f"name must match lowercase kebab-case pattern {SKILL_NAME_PATTERN}"
            )
        return normalized

    @field_validator("description", "instructions")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    @field_validator("human_name")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return normalize_optional_text(value)


class SkillUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=64)
    human_name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=1024)
    instructions: str | None = Field(default=None, max_length=20000)
    is_active: bool | None = None
    is_favorite: bool | None = None
    metadata_json: dict[str, Any] | None = Field(default=None, alias="metadata")

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("name")
    @classmethod
    def normalize_name_when_present(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        if not _SKILL_NAME_RE.fullmatch(normalized):
            raise ValueError(
                f"name must match lowercase kebab-case pattern {SKILL_NAME_PATTERN}"
            )
        return normalized

    @field_validator("description", "instructions")
    @classmethod
    def normalize_required_when_present(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    @field_validator("human_name")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return normalize_optional_text(value)
