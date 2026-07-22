# apps/api/service/tools/schemas.py

"""Pydantic contracts for workspace tool availability."""

from pydantic import BaseModel


class ToolAvailabilityUpdateRequest(BaseModel):
    enabled: bool


class ToolAvailabilityRead(BaseModel):
    tool_name: str
    enabled: bool
