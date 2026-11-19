# apps/api/services/mail_merge/tool_inputs.py

"""The mail merge tools' arguments, and the one personal mailbox a merge sends from."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_ai import ModelRetry

from core.exceptions.general import AppValidationError
from models.integrations import IntegrationConnection
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import IntegrationToolBinding
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.plugin import MailMergeSender
from services.mail_merge.recipients import MAX_EXTRA_COLUMNS, STANDARD_COLUMNS
from utils.validation import validate_bare_email

# What the test send covers; approval needs a test of exactly these values.
MERGE_REVIEW_FIELDS = ("subject", "body_html", "fallbacks")

type CellValue = str | int | float | bool


class MergeRecipientArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Annotated[str, Field(max_length=320, description="One email address, no name.")]
    first_name: Annotated[str | None, Field(max_length=200)] = None
    last_name: Annotated[str | None, Field(max_length=200)] = None
    fields: Annotated[
        dict[str, CellValue] | None,
        Field(
            max_length=MAX_EXTRA_COLUMNS,
            description=(
                "Up to 10 more columns for placeholders, such as company. Name them with "
                "letters, digits and underscores."
            ),
        ),
    ] = None


type MergeSubject = Annotated[
    str,
    Field(min_length=1, max_length=998, description="Subject, with placeholders if needed."),
]
type MergeBody = Annotated[
    str,
    Field(
        min_length=1,
        max_length=50_000,
        description=(
            "HTML body with placeholders, such as <p>Hi {{first_name|there}},</p>. Use simple, "
            "inline-styled HTML. A plain-text alternative is derived automatically."
        ),
    ),
]
type MergeRecipients = Annotated[
    list[MergeRecipientArgs], Field(min_length=1, description="One row per person.")
]
type MergeFallbacks = Annotated[
    dict[str, str] | None,
    Field(description="Text to use when a recipient has no value for a column."),
]


class MailMergeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: MergeSubject
    body_html: MergeBody
    recipients: MergeRecipients
    fallbacks: MergeFallbacks = None

    def rows(self) -> list[dict[str, Any]]:
        """Returns one flat row per recipient, as the merge checks read them.

        Raises:
            AppValidationError: Thrown when an extra column reuses a standard column's name.
        """
        rows: list[dict[str, Any]] = []
        for recipient in self.recipients:
            extras = recipient.fields or {}
            clash = sorted(set(extras) & set(STANDARD_COLUMNS))
            if clash:
                raise AppValidationError(
                    f"Put {', '.join(clash)} in its own column, not in fields.",
                    field="recipients",
                )
            rows.append(
                {
                    "email": recipient.email,
                    "first_name": recipient.first_name,
                    "last_name": recipient.last_name,
                    **{key: _cell_text(value) for key, value in extras.items()},
                }
            )
        return rows


OpenTestSenderFn = Callable[[RuntimeDeps, ResolvedContextEntry], Awaitable[MailMergeSender]]


@dataclass(frozen=True)
class MailMergeToolProvider:
    """What differs between the Gmail and Outlook merge tools."""

    provider_key: str
    # The provider as an operator knows it, such as "Gmail".
    label: str
    binding: IntegrationToolBinding
    # Opens a sender as the acting person inside a request, for the card's test send.
    open_test_sender: OpenTestSenderFn


@dataclass(frozen=True)
class MergeMailbox:
    entry: ResolvedContextEntry
    connection: IntegrationConnection
    address: str


def parse_merge_args(args: Mapping[str, Any]) -> MailMergeArgs:
    """Raises AppValidationError naming the first problem, so the card or agent can fix it."""
    try:
        return MailMergeArgs.model_validate(dict(args))
    except ValidationError as exc:
        error = exc.errors()[0]
        location = ".".join(str(part) for part in error["loc"]) or "recipients"
        raise AppValidationError(
            f"Check {location}: {error['msg']}.", field=str(error["loc"][0])
        ) from None


async def merge_mailbox(deps: RuntimeDeps, provider: MailMergeToolProvider) -> MergeMailbox:
    """Returns the one selected personal mailbox, which must belong to the acting person.

    Raises:
        ModelRetry: Thrown when no mailbox, or more than one, is selected.
    """
    active = deps.active_context
    entries = [
        entry
        for entry in (active.compatible_entries(provider.binding) if active else ())
        if entry.write_allowed
    ]
    if len(entries) != 1:
        raise ModelRetry(
            f"Pick exactly one {provider.label} mailbox you can send from for a mail merge."
        )
    entry = entries[0]
    connection = await deps.db.get(IntegrationConnection, entry.connection_id)
    if connection is None or connection.deleted or connection.owner_user_id != deps.user.id:
        # A merge always sends as the person who approves it, from their own mailbox.
        raise ModelRetry(f"Select your own {provider.label} mailbox for a mail merge.")
    address = entry.display_name.strip()
    try:
        validate_bare_email(address)
    except AppValidationError:
        raise ModelRetry(
            f"The {provider.label} mailbox has no email address. Reconnect it, then try again."
        ) from None
    return MergeMailbox(entry=entry, connection=connection, address=address)


def _cell_text(value: CellValue) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)
