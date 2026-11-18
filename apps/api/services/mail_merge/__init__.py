# apps/api/services/mail_merge/__init__.py

"""Mail merge service exports."""

from services.mail_merge.budget import (
    MailAccountKind,
    SendBudget,
    estimate_merge_finish,
    get_send_budget,
    mail_account_kind,
)
from services.mail_merge.recipients import CheckedRecipient, MergeCheck, check_mail_merge
from services.mail_merge.render import (
    MergeTemplate,
    RenderedEmail,
    content_fingerprint,
    render_merge_email,
)

__all__ = [
    "CheckedRecipient",
    "MailAccountKind",
    "MergeCheck",
    "MergeTemplate",
    "RenderedEmail",
    "SendBudget",
    "check_mail_merge",
    "content_fingerprint",
    "estimate_merge_finish",
    "get_send_budget",
    "mail_account_kind",
    "render_merge_email",
]
