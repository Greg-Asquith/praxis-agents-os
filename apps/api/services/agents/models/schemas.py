# apps/api/services/agents/models/schemas.py

"""Pydantic contracts for agent model catalog routes."""

from typing import Any

from pydantic import BaseModel


class ModelCatalogProvider(BaseModel):
    provider: str
    display_name: str
    configured: bool
    model_count: int


class ModelCatalogEntry(BaseModel):
    id: str
    provider: str
    model: str
    display_name: str
    context_window: int
    supports_tools: bool
    supports_thinking: bool
    supports_vision: bool
    supports_structured_output: bool
    default_settings: dict[str, Any]


class ModelCatalogDefaults(BaseModel):
    agent_model: str | None


class ModelCatalogResponse(BaseModel):
    providers: list[ModelCatalogProvider]
    models: list[ModelCatalogEntry]
    defaults: ModelCatalogDefaults
