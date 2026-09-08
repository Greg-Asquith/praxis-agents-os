# apps/api/integrations/outlook_mail/operations/read_draft.py

"""Reads a complete, bounded draft for approval and a later version check."""

import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.exceptions.integration import IntegrationFailureDisposition, IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy
from services.integrations.previews.sanitize import sanitize_preview_html

from .utils import message_path, reject_draft_attachments


class DraftAddress(BaseModel):
    model_config = ConfigDict(strict=True)

    address: str = Field(min_length=3, max_length=320)
    name: str = Field(default="", max_length=1000)


class DraftRecipient(BaseModel):
    email_address: DraftAddress = Field(alias="emailAddress")


class DraftBody(BaseModel):
    content_type: Literal["html", "text"] = Field(alias="contentType")
    content: str = Field(max_length=50_000)


class DraftSnapshot(BaseModel):
    model_config = ConfigDict(strict=True, populate_by_name=True)

    id: str = Field(min_length=1, max_length=512)
    change_key: str = Field(alias="changeKey", min_length=1, max_length=1000)
    is_draft: Literal[True] = Field(alias="isDraft")
    subject: str = Field(max_length=998)
    web_link: str | None = Field(default=None, alias="webLink", max_length=2000)
    body: DraftBody
    to_recipients: Annotated[list[DraftRecipient], Field(alias="toRecipients", max_length=100)]
    cc_recipients: Annotated[list[DraftRecipient], Field(alias="ccRecipients", max_length=100)]
    bcc_recipients: Annotated[list[DraftRecipient], Field(alias="bccRecipients", max_length=100)]
    reply_to: Annotated[list[DraftRecipient], Field(alias="replyTo", max_length=100)]
    from_address: DraftRecipient | None = Field(default=None, alias="from")
    sender: DraftRecipient | None = None

    def approval_details(self) -> dict:
        raw = self.model_dump(mode="json", by_alias=True)
        fingerprint = hashlib.sha256(
            json.dumps(raw, sort_keys=True, ensure_ascii=True).encode()
        ).hexdigest()
        return {
            "fingerprint": fingerprint,
            "subject": self.subject,
            "body": sanitize_preview_html(self.body.content)
            if self.body.content_type == "html"
            else self.body.content,
            "body_type": self.body.content_type,
            "from": self.from_address.email_address.address
            if self.from_address
            else "Selected mailbox",
            "sender": self.sender.email_address.address if self.sender else "Selected mailbox",
            **{
                key: [item.email_address.address for item in values]
                for key, values in (
                    ("to", self.to_recipients),
                    ("cc", self.cc_recipients),
                    ("bcc", self.bcc_recipients),
                    ("reply_to", self.reply_to),
                )
            },
        }


async def read_draft(client, *, message_id: str) -> DraftSnapshot:
    path = message_path(message_id)
    payload = await client.get(
        path,
        operation="read_draft",
        policy=IntegrationRequestPolicy.READ,
        params={
            "$select": "id,changeKey,isDraft,subject,body,toRecipients,ccRecipients,"
            "bccRecipients,replyTo,from,sender,webLink"
        },
        headers={"Prefer": 'outlook.body-content-type="html"'},
    )
    try:
        draft = DraftSnapshot.model_validate(payload)
        if (
            payload.get("isDraft") is not True
            or draft.id != message_id
            or not (draft.to_recipients or draft.cc_recipients or draft.bcc_recipients)
        ):
            raise ValueError("The draft identity or recipients are invalid.")
    except (ValidationError, ValueError):
        raise IntegrationValidationError(
            "Choose an unsent draft with recipients and a message that can be reviewed in full.",
            provider_key="outlook_mail",
            operation="read_draft",
            failure_disposition=IntegrationFailureDisposition.NOT_DISPATCHED,
            error_code="draft_unavailable",
        ) from None
    await reject_draft_attachments(client, message_id=message_id, operation="read_draft")
    return draft
