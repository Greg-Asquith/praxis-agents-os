# apps/api/integrations/outlook_mail/tools/mutations.py

"""Strict input contracts for Outlook mailbox writes."""

from typing import Annotated, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from core.exceptions.general import AppValidationError
from utils.validation import validate_email

from ..references import OutlookMessageReference


def validate_address(value: str) -> str:
    validate_single_line(value)
    try:
        validate_email(value)
    except AppValidationError:
        raise ValueError("Enter a valid email address.") from None
    if value.count("@") != 1 or any(char.isspace() or char in "<>,;" for char in value):
        raise ValueError("Enter one email address without a display name.")
    return value


def validate_text(value: str) -> str:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("Enter valid Unicode text.") from None
    if any(ord(char) < 32 and char not in "\n\r\t" for char in value):
        raise ValueError("Text cannot contain control characters.")
    return value


def validate_single_line(value: str) -> str:
    validate_text(value)
    if any(char in value for char in "\n\r\t"):
        raise ValueError("Enter a single line of text.")
    return value


type MailAddress = Annotated[
    str, Field(strict=True, min_length=3, max_length=320), AfterValidator(validate_address)
]
type Recipients = Annotated[list[MailAddress], Field(strict=True, min_length=1, max_length=100)]
type OptionalRecipients = Annotated[list[MailAddress], Field(strict=True, max_length=100)]
type Subject = Annotated[
    str, Field(strict=True, min_length=1, max_length=998), AfterValidator(validate_single_line)
]
type MailBody = Annotated[str, Field(strict=True, max_length=50_000), AfterValidator(validate_text)]
type FolderName = Annotated[
    str, Field(strict=True, min_length=1, max_length=500), AfterValidator(validate_single_line)
]


class SendMessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    to: Recipients
    subject: Subject
    body_html: MailBody
    cc: OptionalRecipients | None = None
    bcc: OptionalRecipients | None = None


class ReplyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    message: OutlookMessageReference
    body_html: MailBody
    reply_all: bool = False


class ForwardInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    message: OutlookMessageReference
    to: Recipients
    body_html: MailBody = ""


class DraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    to: Recipients | None = None
    subject: Subject | None = None
    body_html: MailBody = ""
    cc: OptionalRecipients | None = None
    bcc: OptionalRecipients | None = None
    reply_to: OutlookMessageReference | None = None
    reply_all: bool = False

    @model_validator(mode="after")
    def validate_draft_kind(self) -> Self:
        if self.reply_to is not None:
            if self.to is not None or self.subject is not None:
                raise ValueError("A reply draft cannot set To or Subject.")
        elif self.to is None or self.subject is None:
            raise ValueError("A new draft requires To and Subject.")
        elif self.reply_all:
            raise ValueError("Reply all requires a reply target.")
        return self


class MoveInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    message: OutlookMessageReference
    destination_folder: FolderName


class UpdateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    message: OutlookMessageReference
    is_read: bool | None = None
    flagged: bool | None = None

    @model_validator(mode="after")
    def validate_changes(self) -> Self:
        if self.is_read is None and self.flagged is None:
            raise ValueError("Set Read or Flagged to update a message.")
        return self
