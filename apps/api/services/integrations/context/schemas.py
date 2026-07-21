# apps/api/services/integrations/context/schemas.py

"""Pydantic contracts for active integration context APIs."""

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator

from models.integration_context import ActiveContextSelection, IntegrationContextGroup


class _ResourceSelectionValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["resource"] = "resource"
    integration_resource_id: UUID


class _ContextGroupSelectionValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["context_group"] = "context_group"
    context_group_id: UUID


_SelectionValue = Annotated[
    _ResourceSelectionValue | _ContextGroupSelectionValue,
    Field(discriminator="type"),
]


class ActiveContextSelectionValue(RootModel[_SelectionValue]):
    """The strict persisted selection shape used by users and schedules."""

    @property
    def type(self) -> Literal["resource", "context_group"]:
        return self.root.type

    @property
    def integration_resource_id(self) -> UUID | None:
        if isinstance(self.root, _ResourceSelectionValue):
            return self.root.integration_resource_id
        return None

    @property
    def context_group_id(self) -> UUID | None:
        if isinstance(self.root, _ContextGroupSelectionValue):
            return self.root.context_group_id
        return None

    @classmethod
    def for_resource(cls, resource_id: UUID) -> "ActiveContextSelectionValue":
        return cls(_ResourceSelectionValue(integration_resource_id=resource_id))

    @classmethod
    def for_context_group(cls, group_id: UUID) -> "ActiveContextSelectionValue":
        return cls(_ContextGroupSelectionValue(context_group_id=group_id))

    @classmethod
    def from_selection(cls, selection: ActiveContextSelection) -> "ActiveContextSelectionValue":
        if selection.integration_resource_id is not None:
            return cls.for_resource(selection.integration_resource_id)
        if selection.context_group_id is None:
            raise ValueError("Persisted active context selection has no target")
        return cls.for_context_group(selection.context_group_id)


class ResolvedContextEntryRead(BaseModel):
    integration_resource_id: UUID
    provider_key: str
    resource_type: str
    external_id: str
    display_name: str
    connection_id: UUID
    connection_label: str
    connection_status: str
    write_allowed: bool


class UnavailableContextEntryRead(BaseModel):
    display_name: str
    provider_key: str
    reason: str


class ActiveContextRead(BaseModel):
    selection: ActiveContextSelectionValue | None
    entries: list[ResolvedContextEntryRead] = Field(default_factory=list)
    unavailable: list[UnavailableContextEntryRead] = Field(default_factory=list)


class ContextGroupMemberRead(BaseModel):
    id: UUID
    connection_id: UUID
    resource_type: str
    external_id: str
    display_name: str
    enabled: bool
    availability: str


class ContextGroupRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    name: str
    created_by_user_id: UUID | None
    created_at: datetime
    updated_at: datetime
    members: list[ContextGroupMemberRead]

    @classmethod
    def from_group(cls, group: IntegrationContextGroup) -> "ContextGroupRead":
        return cls(
            id=group.id,
            workspace_id=group.workspace_id,
            name=group.name,
            created_by_user_id=group.created_by_user_id,
            created_at=group.created_at,
            updated_at=group.updated_at,
            members=[
                ContextGroupMemberRead(
                    id=member.resource.id,
                    connection_id=member.resource.connection_id,
                    resource_type=member.resource.resource_type,
                    external_id=member.resource.external_id,
                    display_name=member.resource.display_name,
                    enabled=member.resource.enabled,
                    availability=member.resource.availability,
                )
                for member in sorted(
                    group.members,
                    key=lambda item: (item.resource.display_name.casefold(), str(item.resource.id)),
                )
            ],
        )


class ContextGroupListResponse(BaseModel):
    items: list[ContextGroupRead]


class ContextGroupCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    resource_ids: list[UUID] = Field(default_factory=list)


class ContextGroupUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    resource_ids: list[UUID] | None = None

    @model_validator(mode="after")
    def has_update(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field is required")
        return self
