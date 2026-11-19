# apps/api/services/mail_merge/__init__.py

"""Mail merge service exports."""

from services.mail_merge.budget import (
    MailAccountKind,
    SendBudget,
    estimate_merge_finish,
    get_send_budget,
    mail_account_kind,
)
from services.mail_merge.cancel_mail_merge import cancel_mail_merge
from services.mail_merge.get_mail_merge import get_mail_merge
from services.mail_merge.merge_tool_definition import (
    mail_merge_tool_definition,
    run_mail_merge_tool,
)
from services.mail_merge.pause_mail_merge import pause_mail_merge
from services.mail_merge.queue_merge_send import queue_merge_send
from services.mail_merge.recipients import CheckedRecipient, MergeCheck, check_mail_merge
from services.mail_merge.render import (
    MergeTemplate,
    RenderedEmail,
    content_fingerprint,
    render_merge_email,
)
from services.mail_merge.resume_mail_merge import resume_mail_merge
from services.mail_merge.send_merge_chunk import send_merge_chunk
from services.mail_merge.stop_merge_after_job_failure import stop_merge_after_job_failure
from services.mail_merge.stop_user_mail_merges import stop_user_mail_merges
from services.mail_merge.tool_inputs import (
    MailMergeToolProvider,
    MergeBody,
    MergeFallbacks,
    MergeRecipients,
    MergeSubject,
)

__all__ = [
    "CheckedRecipient",
    "MailAccountKind",
    "MailMergeToolProvider",
    "MergeBody",
    "MergeCheck",
    "MergeFallbacks",
    "MergeRecipients",
    "MergeSubject",
    "MergeTemplate",
    "RenderedEmail",
    "SendBudget",
    "cancel_mail_merge",
    "check_mail_merge",
    "content_fingerprint",
    "estimate_merge_finish",
    "get_mail_merge",
    "get_send_budget",
    "mail_account_kind",
    "mail_merge_tool_definition",
    "pause_mail_merge",
    "queue_merge_send",
    "render_merge_email",
    "resume_mail_merge",
    "run_mail_merge_tool",
    "send_merge_chunk",
    "stop_merge_after_job_failure",
    "stop_user_mail_merges",
]
