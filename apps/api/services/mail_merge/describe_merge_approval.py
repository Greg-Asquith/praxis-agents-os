# apps/api/services/mail_merge/describe_merge_approval.py

"""What a mail merge's approval card shows: the checked rows, the budget, and the pace."""

from datetime import UTC, datetime
from typing import Any

from core.exceptions.general import AppValidationError
from core.settings import settings
from services.agents.runtime.context import RuntimeDeps
from services.mail_merge.budget import estimate_merge_finish, get_send_budget
from services.mail_merge.recipients import check_mail_merge
from services.mail_merge.tool_inputs import (
    MailMergeToolProvider,
    MergeMailbox,
    merge_mailbox,
    parse_merge_args,
)
from services.mail_merge.utils import (
    connection_account_kind,
    has_merge_scopes,
    mail_merge_definition,
)

# The card edits these; everything else in the display is server evidence.
_ARG_KEYS = ("subject", "body_html", "fallbacks", "recipients")


async def describe_merge_approval(
    provider: MailMergeToolProvider, deps: RuntimeDeps, args: dict[str, Any]
) -> dict[str, Any]:
    """Returns the arguments with the mailbox, every row's check, and the sending estimate.

    Built from named keys only, so a proposal can't carry evidence of a test it never had.
    """
    display = {key: args[key] for key in _ARG_KEYS if key in args}
    mailbox = await merge_mailbox(deps, provider)
    display["_mailbox"] = {
        "address": mailbox.address,
        "connection_id": str(mailbox.connection.id),
    }
    display["_merge"] = await _merge_evidence(provider, deps, mailbox, args)
    return display


async def _merge_evidence(
    provider: MailMergeToolProvider,
    deps: RuntimeDeps,
    mailbox: MergeMailbox,
    args: dict[str, Any],
) -> dict[str, Any]:
    now = datetime.now(UTC)
    definition = mail_merge_definition(provider.provider_key)
    budget = await get_send_budget(
        deps.db,
        connection_id=mailbox.connection.id,
        kind=connection_account_kind(
            mailbox.connection, provider_key=provider.provider_key, sender_address=mailbox.address
        ),
        now=now,
    )
    evidence: dict[str, Any] = {
        "needs_reconnect": not await has_merge_scopes(deps.db, mailbox.connection, definition),
        "budget": {
            "cap": budget.cap,
            "remaining": budget.remaining,
            "frees_at": budget.frees_at.isoformat() if budget.frees_at else None,
        },
        "interval_seconds": settings.MAIL_MERGE_SEND_INTERVAL_SECONDS,
        "template_problem": None,
        "recipients": [],
        "estimated_finish": None,
    }
    try:
        parsed = parse_merge_args(args)
        check = await check_mail_merge(
            deps.db,
            workspace_id=deps.workspace.id,
            sender_address=mailbox.address,
            subject=parsed.subject,
            body_html=parsed.body_html,
            fallbacks=parsed.fallbacks or {},
            rows=parsed.rows(),
        )
    except AppValidationError as exc:
        # The card shows the problem and blocks approval until the template is fixed.
        evidence["template_problem"] = exc.message
        return evidence
    evidence["recipients"] = [
        {
            "position": row.position,
            "email": row.email,
            "status": row.status,
            "problems": list(row.problems),
            "warnings": list(row.warnings),
            "skip_reason": row.skip_reason,
        }
        for row in check.recipients
    ]
    ready = sum(row.status == "ready" for row in check.recipients)
    if ready:
        evidence["estimated_finish"] = estimate_merge_finish(
            count=ready, budget=budget, now=now
        ).isoformat()
    return evidence
