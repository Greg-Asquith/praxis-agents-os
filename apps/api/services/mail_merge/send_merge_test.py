# apps/api/services/mail_merge/send_merge_test.py

"""Send the approver a test of a proposed merge, from and to their own mailbox."""

import html
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from core.exceptions.general import AppValidationError
from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationError,
    IntegrationFailureDisposition,
    IntegrationPermissionError,
    IntegrationRateLimitError,
    IntegrationSendingLimitError,
)
from models.mail_merge import MailMergeTestSend
from services.agents.runtime.context import RuntimeDeps
from services.audit_events import (
    AuditAction,
    AuditActorType,
    AuditResourceType,
    AuditStatus,
    safe_record_independent_operation_audit_event,
)
from services.audit_events.operations import record_operation_audit_event
from services.email_suppressions import (
    SUPPRESSED_RECIPIENT_ERROR_CODE,
    refuse_suppressed_recipients,
)
from services.integrations.plugin import MailMergeMessage
from services.integrations.utils import integration_failure_code
from services.mail_merge.budget import get_send_budget
from services.mail_merge.describe_merge_approval import describe_merge_approval
from services.mail_merge.recipients import check_mail_merge
from services.mail_merge.render import MAX_SUBJECT_CHARS, content_fingerprint, render_merge_email
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

MAX_TESTS_PER_APPROVAL = 10
TEST_SUBJECT_PREFIX = "[Test] "


async def send_merge_test(
    provider: MailMergeToolProvider, deps: RuntimeDeps, tool_call_id: str, args: dict[str, Any]
) -> dict[str, Any]:
    """Sends the first ready row's email to the sender's own address, then returns the display.

    Only a person's click on the approval card starts this, never the agent. The test passes
    the Do Not Email guard, counts against the mailbox's budget, and is audited.

    Raises:
        AppValidationError: Thrown when the test can't be sent, with what fixes it.
    """
    mailbox = await merge_mailbox(deps, provider)
    parsed = parse_merge_args(args)
    fallbacks = parsed.fallbacks or {}
    check = await check_mail_merge(
        deps.db,
        workspace_id=deps.workspace.id,
        sender_address=mailbox.address,
        subject=parsed.subject,
        body_html=parsed.body_html,
        fallbacks=fallbacks,
        rows=parsed.rows(),
    )
    row = next((row for row in check.recipients if row.status == "ready"), None)
    rendered = render_merge_email(check.template, row.fields).email if row else None
    if row is None or rendered is None:
        raise AppValidationError(
            "No recipient is ready yet. Fix the rows that need attention, then send the test.",
            field="recipients",
        )
    await _check_can_send(provider, deps, tool_call_id, mailbox)
    message = MailMergeMessage(
        to=mailbox.address,
        subject=(TEST_SUBJECT_PREFIX + rendered.subject)[:MAX_SUBJECT_CHARS],
        body_html=(
            '<p style="padding:8px 12px;background:#fef3c7;border-radius:6px">'
            f"Test email. It uses the details of {html.escape(row.email)}.</p>"
            f"{rendered.body_html}"
        ),
    )
    audit = {
        "workspace_id": deps.workspace.id,
        "action": AuditAction.EXECUTE,
        "resource_type": AuditResourceType.MAIL_MERGE,
        "actor_type": AuditActorType.USER,
        "actor_id": deps.user.id,
        "requested_by_user_id": deps.user.id,
    }
    details = {
        "operation": "send_merge_test",
        "provider_key": provider.provider_key,
        "connection_id": str(mailbox.connection.id),
        "run_id": str(deps.run.id),
        "tool_call_id": tool_call_id,
    }
    try:
        await refuse_suppressed_recipients(
            deps.db,
            workspace_id=deps.workspace.id,
            addresses=[mailbox.address],
            provider_key=provider.provider_key,
            operation="send_merge_test",
        )
        sender = await provider.open_test_sender(deps, mailbox.entry)
        draft = await sender.create_draft(message)
        delivery = await sender.send_draft(draft)
    except IntegrationError as exc:
        # The request rolls back, so this audit commits on its own.
        await safe_record_independent_operation_audit_event(
            **audit,
            status=AuditStatus.FAILURE,
            details={**details, "error_code": integration_failure_code(exc)},
        )
        raise AppValidationError(_failure_message(provider, exc), field="body_html") from exc
    now = datetime.now(UTC)
    deps.db.add(
        MailMergeTestSend(
            workspace_id=deps.workspace.id,
            created_by_user_id=deps.user.id,
            connection_id=mailbox.connection.id,
            run_id=deps.run.id,
            tool_call_id=tool_call_id,
            content_fingerprint=content_fingerprint(
                subject=parsed.subject, body_html=parsed.body_html, fallbacks=fallbacks
            ),
            attempted_at=now,
        )
    )
    await record_operation_audit_event(
        deps.db,
        **audit,
        summary="Sent a mail merge test to the sender's own address",
        details={**details, "external_ref": delivery.provider_message_id},
    )
    display = await describe_merge_approval(provider, deps, args)
    display["_test"] = {
        "sent_to": mailbox.address,
        "recipient": row.email,
        "sent_at": now.isoformat(),
    }
    return display


async def _check_can_send(
    provider: MailMergeToolProvider, deps: RuntimeDeps, tool_call_id: str, mailbox: MergeMailbox
) -> None:
    definition = mail_merge_definition(provider.provider_key)
    if not await has_merge_scopes(deps.db, mailbox.connection, definition):
        raise AppValidationError(
            f"Reconnect {provider.label} so Praxis can send mail merges, then send the test.",
            field="body_html",
        )
    tests = await deps.db.scalar(
        select(func.count()).where(
            MailMergeTestSend.run_id == deps.run.id,
            MailMergeTestSend.tool_call_id == tool_call_id,
        )
    )
    if (tests or 0) >= MAX_TESTS_PER_APPROVAL:
        raise AppValidationError(
            f"You've sent {MAX_TESTS_PER_APPROVAL} tests for this mail merge. Approve or decline "
            "it, and ask the agent to prepare a new one if it needs more changes.",
            field="body_html",
        )
    budget = await get_send_budget(
        deps.db,
        connection_id=mailbox.connection.id,
        kind=connection_account_kind(
            mailbox.connection, provider_key=provider.provider_key, sender_address=mailbox.address
        ),
        now=datetime.now(UTC),
    )
    if budget.remaining <= 0:
        raise AppValidationError(
            "This mailbox has used its mail merge allowance for the last 24 hours. "
            "Send the test once there's room again.",
            field="body_html",
        )


def _failure_message(provider: MailMergeToolProvider, exc: IntegrationError) -> str:
    if exc.error_code == SUPPRESSED_RECIPIENT_ERROR_CODE:
        return exc.user_message
    if exc.failure_disposition == IntegrationFailureDisposition.AMBIGUOUS:
        return f"{provider.label} didn't confirm the test. Check your inbox before sending another."
    if isinstance(exc, IntegrationSendingLimitError):
        return f"{provider.label} says this mailbox reached its daily sending limit."
    if isinstance(exc, IntegrationRateLimitError):
        return f"{provider.label} is busy. Wait a minute, then send the test again."
    if isinstance(exc, (IntegrationAuthError, IntegrationPermissionError)):
        return f"Reconnect {provider.label}, then send the test again."
    return f"{provider.label} couldn't send the test. Try again."
