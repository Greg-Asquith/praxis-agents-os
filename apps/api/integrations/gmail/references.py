# apps/api/integrations/gmail/references.py

"""Gmail-owned scoped entity reference types."""

from typing import Literal

from pydantic import Field

from services.integrations.entity_references import ScopedEntityReference


class GmailMessageReference(ScopedEntityReference):
    entity_kind: Literal["gmail_message"] = "gmail_message"
    sender: str | None = Field(default=None, max_length=500)
    date: str | None = Field(default=None, max_length=500)
