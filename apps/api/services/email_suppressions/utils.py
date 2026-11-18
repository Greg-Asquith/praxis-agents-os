# apps/api/services/email_suppressions/utils.py

"""Shared helpers for the Do Not Email list."""

from email_validator import EmailNotValidError, validate_email as validate_email_syntax

from models.email_suppression import WorkspaceEmailSuppression
from models.user import User
from services.email_suppressions.schemas import EmailSuppressionRead
from utils.validation import normalize_email

# Gmail delivers these two domains to one mailbox and ignores dots before the @.
_GMAIL_DOMAINS = frozenset({"gmail.com", "googlemail.com"})


def address_match_key(address: str) -> str:
    """Returns the form shared by addresses that reach the same mailbox.

    Drops a plus-tag on any domain, and dots on Gmail. Erring towards a match is the safe
    side for a list of people not to email.
    """
    address = normalize_email(address)
    local, at, domain = address.rpartition("@")
    if not at:
        return address
    local = local.split("+", 1)[0] or local
    if domain in _GMAIL_DOMAINS:
        return f"{local.replace('.', '')}@gmail.com"
    return f"{local}@{domain}"


def parse_listed_address(value: str) -> str | None:
    """Returns the address as the list stores it, or None when it isn't one valid address."""
    address = normalize_email(value)
    try:
        validate_email_syntax(address, check_deliverability=False)
    except EmailNotValidError:
        return None
    return address


def suppression_read(
    entry: WorkspaceEmailSuppression, creator: User | None
) -> EmailSuppressionRead:
    return EmailSuppressionRead(
        id=entry.id,
        email=entry.email,
        reason=entry.reason,
        source=entry.source,
        created_by_user_id=entry.created_by_user_id,
        created_by_name=(creator.display_name or creator.email) if creator else None,
        created_at=entry.created_at,
    )
