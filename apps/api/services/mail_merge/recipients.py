# apps/api/services/mail_merge/recipients.py

"""Check a merge's template and recipient rows before anyone approves it."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from core.settings import settings
from services.email_suppressions import find_suppressed_recipients
from services.email_suppressions.utils import parse_listed_address
from services.mail_merge.render import MergeTemplate, parse_merge_template, render_merge_email
from utils.validation import normalize_email

STANDARD_COLUMNS = ("email", "first_name", "last_name")
MAX_EXTRA_COLUMNS = 10

_COLUMN_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_NAME_COLUMNS = ("first_name", "last_name")
_ROLE_LOCAL_PARTS = frozenset({"noreply", "no-reply", "postmaster", "mailer-daemon"})

RecipientCheckStatus = Literal["ready", "needs_attention", "skipped"]
SkipReason = Literal["duplicate", "sender", "do_not_email"]


@dataclass(frozen=True)
class CheckedRecipient:
    """One row as the approval shows it. Only ready rows are ever sent."""

    position: int
    email: str
    fields: dict[str, str]
    status: RecipientCheckStatus
    problems: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    # Shown to the operator; a tool result reports only that the row was skipped.
    skip_reason: SkipReason | None = None


@dataclass(frozen=True)
class MergeCheck:
    template: MergeTemplate
    recipients: list[CheckedRecipient]


async def check_mail_merge(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    sender_address: str,
    subject: str,
    body_html: str,
    fallbacks: Mapping[str, str],
    rows: Sequence[Mapping[str, Any]],
) -> MergeCheck:
    """Returns the checked template and every row marked ready, needs attention, or skipped.

    Calls the Do Not Email guard rather than reading the list, and never sends anything.

    Raises:
        AppValidationError: Thrown when the template is invalid, or the rows are empty, too
            many, or have too many or badly named columns.
    """
    columns = _merge_columns(rows)
    template = parse_merge_template(
        subject=subject, body_html=body_html, fallbacks=fallbacks, columns=columns
    )
    values = [
        {column: "" if row.get(column) is None else str(row[column]).strip() for column in columns}
        for row in rows
    ]
    listed = set(
        await find_suppressed_recipients(
            db,
            workspace_id=workspace_id,
            addresses=[
                address
                for row in values
                if (address := parse_listed_address(row["email"])) is not None
            ],
        )
    )
    sender = normalize_email(sender_address)
    seen: set[str] = set()
    recipients: list[CheckedRecipient] = []
    for position, row in enumerate(values):
        email = normalize_email(row["email"])
        valid = parse_listed_address(email) is not None
        skip_reason = (
            _skip_reason(email, sender=sender, seen=seen, listed=listed) if valid else None
        )
        seen.add(email)
        if skip_reason is not None:
            recipients.append(
                CheckedRecipient(
                    position=position,
                    email=email,
                    fields=row,
                    status="skipped",
                    skip_reason=skip_reason,
                )
            )
            continue
        problems = list(render_merge_email(template, row).problems)
        if not valid:
            problems.insert(0, "This isn't a valid email address.")
        recipients.append(
            CheckedRecipient(
                position=position,
                email=email,
                fields=row,
                status="needs_attention" if problems else "ready",
                problems=tuple(problems),
                warnings=_warnings(email, row),
            )
        )
    return MergeCheck(template=template, recipients=recipients)


def _merge_columns(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    if not rows:
        raise AppValidationError("Add at least one recipient.", field="recipients")
    limit = settings.MAIL_MERGE_MAX_RECIPIENTS
    if len(rows) > limit:
        raise AppValidationError(
            f"A mail merge can have at most {limit} recipients.", field="recipients"
        )
    extras = list(dict.fromkeys(key for row in rows for key in row if key not in STANDARD_COLUMNS))
    if len(extras) > MAX_EXTRA_COLUMNS:
        raise AppValidationError(
            f"Use at most {MAX_EXTRA_COLUMNS} columns besides email and names.",
            field="recipients",
        )
    invalid = [name for name in extras if not _COLUMN_NAME.fullmatch(name)]
    if invalid:
        raise AppValidationError(
            "Name columns with letters, digits and underscores, starting with a letter: "
            f"{', '.join(invalid)}.",
            field="recipients",
        )
    return [*STANDARD_COLUMNS, *extras]


def _skip_reason(email: str, *, sender: str, seen: set[str], listed: set[str]) -> SkipReason | None:
    if email == sender:
        return "sender"
    if email in seen:
        return "duplicate"
    if email in listed:
        return "do_not_email"
    return None


def _warnings(email: str, row: Mapping[str, str]) -> tuple[str, ...]:
    warnings: list[str] = []
    for column in _NAME_COLUMNS:
        name = row.get(column, "")
        label = column.replace("_", " ")
        if "@" in name or any(char.isdigit() for char in name):
            warnings.append(f"The {label} looks like it isn't a name.")
        elif len(name) > 1 and name.isupper():
            warnings.append(f"The {label} is all capitals.")
        elif len(name) > 1 and name.islower():
            warnings.append(f"The {label} is all lower case.")
    if email.partition("@")[0] in _ROLE_LOCAL_PARTS:
        warnings.append("This address doesn't reach a person.")
    return tuple(warnings)
