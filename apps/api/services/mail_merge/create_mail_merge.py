# apps/api/services/mail_merge/create_mail_merge.py

"""Record an approved mail merge and queue its background sending. No email is sent here."""

from datetime import UTC, datetime
from typing import Any

from pydantic_ai import ModelRetry, RunContext
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from core.exceptions.general import AppValidationError
from models.integrations import IntegrationConnection
from models.mail_merge import MailMerge, MailMergeRecipient
from services.agents.runtime.context import RuntimeDeps
from services.email_suppressions.utils import parse_listed_address
from services.integrations.approved_display_args import approved_display_args
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.context.targeted import run_context_scope
from services.mail_merge.budget import estimate_merge_finish, get_send_budget
from services.mail_merge.domain import RECIPIENT_STATUS_PENDING, RECIPIENT_STATUS_SKIPPED
from services.mail_merge.queue_merge_send import queue_merge_send
from services.mail_merge.recipients import CheckedRecipient, check_mail_merge
from services.mail_merge.render import content_fingerprint
from services.mail_merge.tool_inputs import (
    MailMergeArgs,
    MailMergeToolProvider,
    MergeMailbox,
    merge_mailbox,
)
from services.mail_merge.utils import (
    connection_account_kind,
    has_merge_scopes,
    mail_merge_definition,
)


async def create_mail_merge(
    provider: MailMergeToolProvider, ctx: RunContext[RuntimeDeps], args: MailMergeArgs
) -> dict[str, Any]:
    """Checks the approved rows again, stores the merge, and queues its first send job.

    Running the same tool call again returns the merge it already created. A mailbox that
    needs reconnecting, is already sending another merge, or has no ready row gives a failed
    result with the reason.

    Raises:
        ModelRetry: Thrown when the selected mailbox changed since approval.
    """
    mailbox = await merge_mailbox(ctx.deps, provider)
    approved = approved_display_args(ctx).get("_mailbox")
    if not isinstance(approved, dict) or approved.get("connection_id") != str(
        mailbox.connection.id
    ):
        raise ModelRetry(
            "The selected mailbox changed after approval. Prepare the mail merge again."
        )

    async def operation(_entry: ResolvedContextEntry) -> dict[str, Any]:
        return await _record_merge(provider, ctx, args, mailbox)

    results = await run_context_scope(
        ctx,
        binding=provider.binding,
        provider_scope_id=mailbox.entry.external_id,
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


async def _record_merge(
    provider: MailMergeToolProvider,
    ctx: RunContext[RuntimeDeps],
    args: MailMergeArgs,
    mailbox: MergeMailbox,
) -> dict[str, Any]:
    deps = ctx.deps
    existing = await deps.db.scalar(
        select(MailMerge).where(
            MailMerge.run_id == deps.run.id, MailMerge.tool_call_id == ctx.tool_call_id
        )
    )
    if existing is not None:
        return await _result(deps, existing, mailbox.connection)
    if not await has_merge_scopes(
        deps.db, mailbox.connection, mail_merge_definition(provider.provider_key)
    ):
        raise AppValidationError(
            f"Reconnect {provider.label} so Praxis can send mail merges, then try again."
        )
    fallbacks = args.fallbacks or {}
    check = await check_mail_merge(
        deps.db,
        workspace_id=deps.workspace.id,
        sender_address=mailbox.address,
        subject=args.subject,
        body_html=args.body_html,
        fallbacks=fallbacks,
        rows=args.rows(),
    )
    if not any(row.status == "ready" for row in check.recipients):
        raise AppValidationError("No recipient was ready, so nothing was sent.")
    merge = MailMerge(
        workspace_id=deps.workspace.id,
        created_by_user_id=deps.user.id,
        connection_id=mailbox.connection.id,
        run_id=deps.run.id,
        tool_call_id=ctx.tool_call_id,
        provider_key=provider.provider_key,
        sender_address=mailbox.address,
        subject_template=check.template.subject,
        body_template=check.template.body_html,
        fallbacks=dict(fallbacks),
        content_fingerprint=content_fingerprint(
            subject=args.subject, body_html=args.body_html, fallbacks=fallbacks
        ),
    )
    try:
        async with deps.db.begin_nested():
            deps.db.add(merge)
            await deps.db.flush()
            deps.db.add_all(_recipient_rows(merge, check.recipients))
            await queue_merge_send(deps.db, merge=merge)
    except IntegrityError:
        raise AppValidationError(
            "Another mail merge is still sending from this mailbox. Wait for it to finish, "
            "then send this one again."
        ) from None
    # The job must be visible to workers now, not when the turn ends.
    await deps.db.commit()
    return await _result(deps, merge, mailbox.connection)


def _recipient_rows(
    merge: MailMerge, recipients: list[CheckedRecipient]
) -> list[MailMergeRecipient]:
    """Ready rows wait to send; other valid, distinct addresses are kept as skipped."""
    rows: list[MailMergeRecipient] = []
    stored: set[str] = set()
    for recipient in recipients:
        if recipient.email in stored or parse_listed_address(recipient.email) is None:
            continue
        stored.add(recipient.email)
        ready = recipient.status == "ready"
        rows.append(
            MailMergeRecipient(
                workspace_id=merge.workspace_id,
                merge_id=merge.id,
                position=recipient.position,
                email=recipient.email,
                fields=recipient.fields,
                status=RECIPIENT_STATUS_PENDING if ready else RECIPIENT_STATUS_SKIPPED,
                error_code=None if ready else recipient.skip_reason or "needs_attention",
            )
        )
    return rows


async def _result(
    deps: RuntimeDeps, merge: MailMerge, connection: IntegrationConnection
) -> dict[str, Any]:
    """What the agent learns: counts and timing, never which rows were skipped or why."""
    counts = dict(
        (
            await deps.db.execute(
                select(MailMergeRecipient.status, func.count())
                .where(MailMergeRecipient.merge_id == merge.id)
                .group_by(MailMergeRecipient.status)
            )
        ).all()
    )
    skipped = counts.get(RECIPIENT_STATUS_SKIPPED, 0)
    pending = counts.get(RECIPIENT_STATUS_PENDING, 0)
    now = datetime.now(UTC)
    finish = None
    if pending:
        budget = await get_send_budget(
            deps.db,
            connection_id=connection.id,
            kind=connection_account_kind(
                connection, provider_key=merge.provider_key, sender_address=merge.sender_address
            ),
            now=now,
        )
        finish = estimate_merge_finish(count=pending, budget=budget, now=now).isoformat()
    return {
        "merge_id": str(merge.id),
        "status": merge.status,
        "sender": merge.sender_address,
        "sending_to": sum(counts.values()) - skipped,
        "not_sent": skipped,
        "estimated_finish": finish,
        # Models otherwise tend to ask the user to approve a merge they already approved.
        "message": (
            "The user approved this mail merge and it is sending in the background. Nothing "
            "else needs approving. Its card in the conversation shows progress, with Pause "
            "and Cancel."
        ),
    }
