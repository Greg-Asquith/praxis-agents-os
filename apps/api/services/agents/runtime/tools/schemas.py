# apps/api/services/agents/runtime/tools/schemas.py

"""Pydantic contracts for runtime tool catalog routes."""

from pydantic import BaseModel

from services.agents.runtime.tools.contract import RuntimeToolDefinition


class ToolCatalogEntry(BaseModel):
    name: str
    provider: str
    label: str
    description: str
    effect: str
    default_policy: str
    supported_policies: list[str]
    defer_loading: bool

    @classmethod
    def from_definition(cls, definition: RuntimeToolDefinition) -> "ToolCatalogEntry":
        return cls(
            name=definition.name,
            provider=definition.provider,
            label=definition.label,
            description=definition.description,
            effect=definition.effect,
            default_policy=definition.default_policy,
            supported_policies=sorted(definition.allowed_policies()),
            defer_loading=definition.defer_loading,
        )


class ToolCatalogResponse(BaseModel):
    tools: list[ToolCatalogEntry]
