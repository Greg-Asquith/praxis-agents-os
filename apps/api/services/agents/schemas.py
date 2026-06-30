# apps/api/services/agents/schemas.py

"""Pydantic contracts for agent configuration routes."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.agent import Agent

ToolPolicyValue = Literal["auto", "approval"]


class AgentRead(BaseModel):
    id: UUID
    name: str
    slug: str
    description: str | None = None
    instructions: str
    workspace_id: UUID
    created_by: UUID
    tool_names: list[str]
    tool_policies: dict[str, str] | None = None
    skill_ids: list[UUID]
    allowed_agent_ids: list[UUID]
    model_provider: str | None = None
    model: str | None = None
    model_settings: dict[str, Any] | None = None
    azure_deployment: str | None = None
    max_steps: int | None = None
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
    def from_agent(cls, agent: Agent) -> "AgentRead":
        return cls.model_validate(agent)


class AgentsListResponse(BaseModel):
    agents: list[AgentRead]
    total: int
    limit: int
    offset: int


class AgentCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=5000)
    instructions: str = Field(min_length=1, max_length=20000)
    tool_names: list[str] = Field(default_factory=list, max_length=100)
    tool_policies: dict[str, ToolPolicyValue] | None = None
    skill_ids: list[UUID] = Field(default_factory=list, max_length=100)
    allowed_agent_ids: list[UUID] = Field(default_factory=list, max_length=100)
    model_provider: str | None = Field(default=None, max_length=50)
    model: str | None = Field(default=None, max_length=100)
    model_settings: dict[str, Any] | None = None
    azure_deployment: str | None = Field(default=None, max_length=100)
    max_steps: int | None = Field(default=20, ge=1, le=100)
    is_active: bool = True
    is_favorite: bool = False
    metadata_json: dict[str, Any] | None = Field(default=None, alias="metadata")

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("name", "instructions")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    @field_validator(
        "slug",
        "description",
        "model_provider",
        "model",
        "azure_deployment",
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        return normalized

    @field_validator("tool_names")
    @classmethod
    def normalize_tool_names(cls, value: list[str]) -> list[str]:
        return _normalize_text_list(value, field_name="tool_names")

    @field_validator("tool_policies")
    @classmethod
    def normalize_tool_policies(
        cls,
        value: dict[str, ToolPolicyValue] | None,
    ) -> dict[str, ToolPolicyValue] | None:
        return _normalize_tool_policy_keys(value)


class AgentUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    slug: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=5000)
    instructions: str | None = Field(default=None, max_length=20000)
    tool_names: list[str] | None = Field(default=None, max_length=100)
    tool_policies: dict[str, ToolPolicyValue] | None = None
    skill_ids: list[UUID] | None = Field(default=None, max_length=100)
    allowed_agent_ids: list[UUID] | None = Field(default=None, max_length=100)
    model_provider: str | None = Field(default=None, max_length=50)
    model: str | None = Field(default=None, max_length=100)
    model_settings: dict[str, Any] | None = None
    azure_deployment: str | None = Field(default=None, max_length=100)
    max_steps: int | None = Field(default=None, ge=1, le=100)
    is_active: bool | None = None
    is_favorite: bool | None = None
    metadata_json: dict[str, Any] | None = Field(default=None, alias="metadata")

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("name", "instructions")
    @classmethod
    def normalize_required_when_present(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    @field_validator(
        "slug",
        "description",
        "model_provider",
        "model",
        "azure_deployment",
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        return normalized

    @field_validator("tool_names")
    @classmethod
    def normalize_tool_names(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return _normalize_text_list(value, field_name="tool_names")

    @field_validator("tool_policies")
    @classmethod
    def normalize_tool_policies(
        cls,
        value: dict[str, ToolPolicyValue] | None,
    ) -> dict[str, ToolPolicyValue] | None:
        return _normalize_tool_policy_keys(value)


def _normalize_text_list(value: list[str], *, field_name: str) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        clean = item.strip()
        if not clean:
            raise ValueError(f"{field_name} must not contain blank values")
        if clean not in seen:
            normalized.append(clean)
            seen.add(clean)
    return normalized


def _normalize_tool_policy_keys(
    value: dict[str, ToolPolicyValue] | None,
) -> dict[str, ToolPolicyValue] | None:
    if value is None:
        return None
    normalized: dict[str, ToolPolicyValue] = {}
    for raw_name, policy in value.items():
        name = raw_name.strip()
        if not name:
            raise ValueError("tool_policies must not contain blank tool names")
        if name in normalized:
            raise ValueError("tool_policies contains duplicate tool names")
        normalized[name] = policy
    return normalized
