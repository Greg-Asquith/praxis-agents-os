# apps/api/services/agents/runtime/tools/schemas.py

"""Pydantic contracts for runtime tool catalog routes."""

from pydantic import BaseModel

from services.agents.runtime.tools.contract import RuntimeToolDefinition, ToolPresentation


class ToolFieldPresentationRead(BaseModel):
    key: str
    label: str
    format: str
    editable: bool


class ToolPresentationRead(BaseModel):
    icon: str
    running_label: str
    completed_label: str
    failed_label: str
    approval_title: str
    approval_prompt: str
    arg_fields: list[ToolFieldPresentationRead]
    result_fields: list[ToolFieldPresentationRead]

    @classmethod
    def from_presentation(cls, presentation: ToolPresentation) -> "ToolPresentationRead":
        return cls(
            icon=presentation.icon,
            running_label=presentation.running_label,
            completed_label=presentation.completed_label,
            failed_label=presentation.failed_label,
            approval_title=presentation.approval_title,
            approval_prompt=presentation.approval_prompt,
            arg_fields=[
                ToolFieldPresentationRead(
                    key=field.key,
                    label=field.label,
                    format=field.format,
                    editable=field.editable,
                )
                for field in presentation.arg_fields
            ],
            result_fields=[
                ToolFieldPresentationRead(
                    key=field.key,
                    label=field.label,
                    format=field.format,
                    editable=field.editable,
                )
                for field in presentation.result_fields
            ],
        )


class ToolPresentationEntry(BaseModel):
    name: str
    provider: str
    label: str
    effect: str
    ui: ToolPresentationRead

    @classmethod
    def from_definition(cls, definition: RuntimeToolDefinition) -> "ToolPresentationEntry":
        return cls(
            name=definition.name,
            provider=definition.provider,
            label=definition.label,
            effect=definition.effect,
            ui=ToolPresentationRead.from_presentation(definition.presentation),
        )


class ToolPresentationsResponse(BaseModel):
    tools: list[ToolPresentationEntry]


class ToolCatalogEntry(BaseModel):
    name: str
    provider: str
    label: str
    description: str
    kind: str
    effect: str
    effect_scope: str
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
            kind=definition.kind,
            effect=definition.effect,
            effect_scope=definition.effect_scope,
            default_policy=definition.default_policy,
            supported_policies=sorted(definition.allowed_policies()),
            defer_loading=definition.defer_loading,
        )


class ToolCatalogResponse(BaseModel):
    tools: list[ToolCatalogEntry]
