# apps/api/services/mail_merge/__init__.py

"""Mail merge service exports."""

from services.mail_merge.budget import (
    MailAccountKind,
    SendBudget,
    estimate_merge_finish,
    get_send_budget,
    mail_account_kind,
)
from services.mail_merge.queue_merge_send import queue_merge_send
from services.mail_merge.recipients import CheckedRecipient, MergeCheck, check_mail_merge
from services.mail_merge.render import (
    MergeTemplate,
    RenderedEmail,
    content_fingerprint,
    render_merge_email,
)
from services.mail_merge.send_merge_chunk import send_merge_chunk
from services.mail_merge.stop_merge_after_job_failure import stop_merge_after_job_failure
from services.mail_merge.stop_user_mail_merges import stop_user_mail_merges

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
    "queue_merge_send",
    "render_merge_email",
    "send_merge_chunk",
    "stop_merge_after_job_failure",
    "stop_user_mail_merges",
]
