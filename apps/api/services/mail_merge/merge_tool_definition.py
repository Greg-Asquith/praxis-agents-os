# apps/api/services/mail_merge/merge_tool_definition.py

"""Build a provider's mail merge tool; Gmail and Outlook differ only in their mailbox."""

from collections.abc import Callable
from functools import partial
from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic_ai import RunContext

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_EXTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_EGRESS_EXTERNAL_WRITE,
    TOOL_POLICY_APPROVAL,
    RuntimeToolDefinition,
    ToolFieldColumn,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput
from services.mail_merge.create_mail_merge import create_mail_merge
from services.mail_merge.describe_merge_approval import describe_merge_approval
from services.mail_merge.recipients import MAX_EXTRA_COLUMNS
from services.mail_merge.send_merge_test import send_merge_test
from services.mail_merge.tool_inputs import (
    MERGE_REVIEW_FIELDS,
    MailMergeArgs,
    MailMergeToolProvider,
    MergeRecipientArgs,
)


class MailMergeData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merge_id: str
    status: str
    sender: str
    sending_to: int
    not_sent: int
    estimated_finish: str | None = None
    message: str


class MailMergeEntry(IntegrationFanOutEntry):
    data: MailMergeData | None = None


class MailMergeOutput(IntegrationFanOutOutput):
    results: list[MailMergeEntry]


async def run_mail_merge_tool(
    provider: MailMergeToolProvider,
    ctx: RunContext[RuntimeDeps],
    *,
    subject: str,
    body_html: str,
    recipients: list[MergeRecipientArgs],
    fallbacks: dict[str, str] | None,
) -> dict[str, Any]:
    """Records the approved merge and queues it; each provider's tool calls only this."""
    args = MailMergeArgs(
        subject=subject, body_html=body_html, recipients=recipients, fallbacks=fallbacks
    )
    return await create_mail_merge(provider, ctx, args)


def mail_merge_tool_definition(
    provider: MailMergeToolProvider,
    *,
    name: str,
    function: Callable[..., Any],
    send_tool_name: str,
    availability_check: Callable[[], bool],
) -> RuntimeToolDefinition:
    label = provider.label
    return RuntimeToolDefinition(
        name=name,
        function=function,
        description=(
            f"Sends one personal email to each recipient from the selected {label} mailbox, "
            "in the background after the user approves. Write the subject and body once with "
            "placeholders such as {{first_name}}, or {{first_name|there}} for a fallback; "
            "Praxis fills them in for each person. Put any other placeholder values in a "
            "recipient's fields. Use this whenever the same message goes to more than a few "
            f"people, never {send_tool_name} in a loop. At most 500 recipients. The user sends "
            "themselves a test from the approval card before approving. A result means the "
            "user approved and the emails are sending; the card shows progress."
        ),
        provider=provider.provider_key,
        label=f"Send {label} Mail Merge",
        code_eligible=False,
        effect=TOOL_EFFECT_WRITE,
        effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
        egress=TOOL_EGRESS_EXTERNAL_WRITE,
        default_policy=TOOL_POLICY_APPROVAL,
        supports_auto=False,
        takes_ctx=True,
        timeout=60,
        output_model=MailMergeOutput,
        integration_binding=provider.binding,
        availability_check=availability_check,
        approval_display_args=partial(describe_merge_approval, provider),
        approval_review_fields=MERGE_REVIEW_FIELDS,
        approval_review_action=partial(send_merge_test, provider),
        presentation=ToolPresentation(
            icon=provider.provider_key,
            running_label="Starting Mail Merge",
            completed_label="Mail Merge Started",
            failed_label="Couldn't Start Mail Merge",
            approval_title="Send Mail Merge",
            approval_prompt=f"The agent wants to send a mail merge from your {label} mailbox.",
            approve_label="Approve & Send",
            arg_fields=(
                ToolFieldPresentation(key="subject", label="Subject", editable=True),
                ToolFieldPresentation(
                    key="body_html", label="Message", format="html", editable=True
                ),
                ToolFieldPresentation(
                    key="fallbacks",
                    label="Fallbacks",
                    format="keyvalue",
                    editable=True,
                    secondary=True,
                ),
                ToolFieldPresentation(
                    key="recipients",
                    label="Recipients",
                    format="records",
                    editable=True,
                    min_rows=1,
                    columns=(
                        ToolFieldColumn(key="email", label="Email", required=True),
                        ToolFieldColumn(key="first_name", label="First Name"),
                        ToolFieldColumn(key="last_name", label="Last Name"),
                        ToolFieldColumn(
                            key="fields",
                            label="Other Columns",
                            format="keyvalue",
                            max_entries=MAX_EXTRA_COLUMNS,
                        ),
                    ),
                ),
            ),
        ),
    )
