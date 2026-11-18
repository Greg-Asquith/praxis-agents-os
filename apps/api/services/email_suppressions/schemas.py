# apps/api/services/email_suppressions/schemas.py

"""Pydantic contracts for the Do Not Email list routes."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from models.email_suppression import EMAIL_SUPPRESSION_REASON_MAX_CHARS
from utils.pagination import OffsetPage

MAX_ADDRESSES_PER_ADD = 1_000


class EmailSuppressionRead(BaseModel):
    id: UUID
    email: str
    reason: str
    source: str
    created_by_user_id: UUID | None
    created_by_name: str | None
    created_at: datetime


class EmailSuppressionListResponse(OffsetPage):
    entries: list[EmailSuppressionRead]


class EmailSuppressionAddRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    addresses: Annotated[
        list[Annotated[str, StringConstraints(max_length=1_000)]],
        Field(min_length=1, max_length=MAX_ADDRESSES_PER_ADD),
    ]
    reason: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=EMAIL_SUPPRESSION_REASON_MAX_CHARS
        ),
    ]


class EmailSuppressionAddResponse(BaseModel):
    added: list[EmailSuppressionRead]
    already_listed: list[str]
    invalid: list[str]
