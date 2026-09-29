# apps/api/services/tools/schemas.py

"""Pydantic contracts for workspace tool settings."""

from pydantic import BaseModel

from services.agents.runtime.tools.contract import ToolPolicy


class ToolAvailabilityUpdateRequest(BaseModel):
    enabled: bool


class ToolAvailabilityRead(BaseModel):
    tool_name: str
    enabled: bool


class ToolPolicyUpdateRequest(BaseModel):
    policy: ToolPolicy | None


class ToolPolicyRead(BaseModel):
    tool_name: str
    policy: ToolPolicy | None
    effective_policy: ToolPolicy


class ToolSettingRead(BaseModel):
    name: str
    provider: str
    label: str
    description: str
    effect: str
    default_policy: ToolPolicy
    supported_policies: list[ToolPolicy]
    enabled: bool
    policy: ToolPolicy | None


class ToolSettingsResponse(BaseModel):
    tools: list[ToolSettingRead]
