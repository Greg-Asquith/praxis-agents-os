# apps/api/integrations/gmail/references.py

"""Gmail-owned scoped entity reference types."""

from typing import ClassVar, Literal

from pydantic import Field

from services.integrations.entity_references import ScopedEntityReference


class GmailMessageReference(ScopedEntityReference):
    entity_kind: Literal["gmail_message"] = "gmail_message"
    mailbox_id: str = Field(
        min_length=1,
        max_length=320,
        description="Provider-owned Gmail mailbox identifier.",
    )
    message_id: str = Field(min_length=1, max_length=512, description="Gmail message ID.")
    sender: str | None = Field(default=None, max_length=500)
    date: str | None = Field(default=None, max_length=500)
    identity_fields: ClassVar[tuple[str, ...]] = (
        *ScopedEntityReference.identity_fields,
        "mailbox_id",
        "message_id",
    )

    @property
    def provider_scope_id(self) -> str:
        return self.mailbox_id

    @property
    def provider_entity_id(self) -> str:
        return self.message_id
