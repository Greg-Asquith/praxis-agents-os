# apps/api/services/integrations/table_scopes/schemas.py

"""Request and response contracts for integration table row scopes."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class TableScopeRuleInput(BaseModel):
    resource_id: UUID
    table_external_id: str = Field(min_length=1, max_length=1024)
    column_name: str = Field(min_length=1, max_length=300)
    allowed_values: list[str] = Field(min_length=1, max_length=200)


class TableScopeReplaceRequest(BaseModel):
    rules: list[TableScopeRuleInput] = Field(max_length=200)


class TableScopeRuleRead(BaseModel):
    id: UUID
    resource_id: UUID
    resource_external_id: str
    resource_display_name: str
    table_external_id: str
    column_name: str
    column_type: Literal["string", "integer"]
    allowed_values: list[str]


class TableScopeListResponse(BaseModel):
    connection_id: UUID
    rules: list[TableScopeRuleRead]


class EligibleTableScopeColumnRead(BaseModel):
    name: str
    column_type: Literal["string", "integer"]
    description: str | None = None


class TableScopeTableRead(BaseModel):
    table_external_id: str
    description: str | None = None
    columns: list[EligibleTableScopeColumnRead]


class TableScopeTableListResponse(BaseModel):
    connection_id: UUID
    resource_id: UUID
    tables: list[TableScopeTableRead]
    next_cursor: str | None = None
