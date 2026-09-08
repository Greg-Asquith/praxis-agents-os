# apps/api/integrations/outlook_mail/references.py

"""Scoped Outlook message and attachment references."""

from typing import ClassVar, Literal

from pydantic import Field

from services.integrations.entity_references import ScopedEntityReference


class OutlookMessageReference(ScopedEntityReference):
    entity_kind: Literal["outlook_message"] = "outlook_message"
    mailbox_id: str = Field(min_length=1, max_length=320)
    message_id: str = Field(min_length=1, max_length=512)
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


class OutlookAttachmentReference(ScopedEntityReference):
    entity_kind: Literal["outlook_attachment"] = "outlook_attachment"
    mailbox_id: str = Field(min_length=1, max_length=320)
    message_id: str = Field(min_length=1, max_length=512)
    attachment_id: str = Field(min_length=1, max_length=512)
    identity_fields: ClassVar[tuple[str, ...]] = (
        *ScopedEntityReference.identity_fields,
        "mailbox_id",
        "message_id",
        "attachment_id",
    )

    @property
    def provider_scope_id(self) -> str:
        return self.mailbox_id

    @property
    def provider_entity_id(self) -> str:
        return self.attachment_id
