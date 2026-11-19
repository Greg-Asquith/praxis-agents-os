# apps/api/tests/services/mail_merge/test_merge_approval.py

"""The required test send, the approval it unlocks, and recording the approved merge."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from functools import partial
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import set_session_tenant_context
from core.exceptions.general import AppValidationError
from integrations.gmail.tools.send_mail_merge import DEFINITION
from integrations.gmail.tools.utils import GMAIL_WRITE_BINDING
from models.agent import Agent
from models.agent_run import AgentRun
from models.jobs import Job
from models.mail_merge import MailMerge, MailMergeRecipient
from models.workspace import WorkspaceMembership
from services.agent_runs.utils import build_review_display_args, validate_retained_review
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from services.integrations import plugin as plugin_module
from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry
from services.integrations.context.results import IntegrationContextResult
from services.integrations.plugin import (
    IntegrationMailMergeDefinition,
    MailMergeDelivery,
    MailMergeDraft,
    MailMergeMessage,
)
from services.mail_merge import create_mail_merge as create_module
from services.mail_merge.budget import MailAccountKind, get_send_budget
from services.mail_merge.create_mail_merge import create_mail_merge
from services.mail_merge.describe_merge_approval import describe_merge_approval
from services.mail_merge.send_merge_test import send_merge_test
from services.mail_merge.tool_inputs import MailMergeArgs, MailMergeToolProvider
from tests.factories import build_conversation, build_user, build_workspace
from tests.factories.integrations import build_external_credential, build_integration_connection
from tests.factories.workspaces import build_workspace_membership

pytestmark = pytest.mark.asyncio

COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
SENDER = "sasha@example.org"
ARGS: dict[str, Any] = {
    "subject": "Hello {{first_name}}",
    "body_html": "<p>Hi {{first_name|there}}</p>",
    "recipients": [
        {"email": "dana@example.com", "first_name": "Dana"},
        {"email": "kai@example.com", "first_name": "Kai", "fields": {"company": "Acme"}},
    ],
}


class RecordingMailbox:
    def __init__(self) -> None:
        self.sent: list[MailMergeMessage] = []

    async def create_draft(self, message: MailMergeMessage) -> MailMergeDraft:
        self.sent.append(message)
        return MailMergeDraft(draft_id=f"draft-{len(self.sent)}")

    async def send_draft(self, draft: MailMergeDraft) -> MailMergeDelivery:
        return MailMergeDelivery(state="sent", provider_message_id=f"message-{draft.draft_id}")

    async def check_draft(self, draft: MailMergeDraft) -> MailMergeDelivery:
        return MailMergeDelivery(state="sent")


@dataclass
class Approval:
    deps: Any
    provider: MailMergeToolProvider
    mailbox: RecordingMailbox
    membership: WorkspaceMembership


@pytest.fixture
async def approval(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> Approval:
    user = build_user(email=f"sender-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"merge-{uuid4().hex[:8]}")
    credential = build_external_credential(provider_key="gmail", granted_scopes=[COMPOSE_SCOPE])
    db_session.add_all([user, workspace, credential])
    await db_session.flush()
    membership = build_workspace_membership(workspace_id=workspace.id, user_id=user.id)
    connection = build_integration_connection(
        credential=credential, user=user, owner_user_id=user.id
    )
    agent = Agent(
        name="Merge Agent",
        slug=f"merge-agent-{uuid4().hex[:8]}",
        instructions="Send mail merges.",
        workspace_id=workspace.id,
        created_by=user.id,
        model_provider="openai",
        model="gpt-6-luna",
    )
    db_session.add_all([membership, connection, agent])
    await db_session.flush()
    conversation = build_conversation(user=user, workspace=workspace, active_agent_id=agent.id)
    db_session.add(conversation)
    await db_session.flush()
    run = AgentRun(
        conversation_id=conversation.id,
        agent_id=agent.id,
        workspace_id=workspace.id,
        user_id=user.id,
        trigger="interactive",
        status="awaiting_approval",
    )
    db_session.add(run)
    await db_session.flush()
    await set_session_tenant_context(db_session, workspace_id=workspace.id, user_id=user.id)
    mailbox = RecordingMailbox()

    async def open_test_sender(deps: Any, entry: Any) -> RecordingMailbox:
        return mailbox

    monkeypatch.setitem(
        plugin_module.PROVIDER_PLUGINS,
        "gmail",
        SimpleNamespace(
            mail_merge=IntegrationMailMergeDefinition(
                open_sender=lambda db, connection: mailbox,
                required_scopes=frozenset({COMPOSE_SCOPE}),
            )
        ),
    )
    entry = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="gmail",
        resource_type="gmail_mailbox",
        external_id=SENDER,
        display_name=SENDER,
        connection_id=connection.id,
        connection_label="Gmail",
        connection_status="active",
        write_allowed=True,
        is_personal=True,
    )
    deps = SimpleNamespace(
        db=db_session,
        user=user,
        workspace=workspace,
        membership=membership,
        run=run,
        conversation=conversation,
        agent=agent,
        active_context=ResolvedActiveContext(source="conversation", entries=(entry,)),
    )
    provider = MailMergeToolProvider(
        provider_key="gmail",
        label="Gmail",
        binding=GMAIL_WRITE_BINDING,
        open_test_sender=open_test_sender,
    )
    return Approval(deps=deps, provider=provider, mailbox=mailbox, membership=membership)


async def test_a_test_goes_only_to_the_sender_and_counts_against_the_budget(
    approval: Approval,
) -> None:
    deps = approval.deps

    display = await send_merge_test(approval.provider, deps, "call-1", ARGS)

    [message] = approval.mailbox.sent
    assert message.to == SENDER
    assert message.subject == "[Test] Hello Dana"
    assert "dana@example.com" in message.body_html
    assert display["_test"]["recipient"] == "dana@example.com"
    budget = await get_send_budget(
        deps.db,
        connection_id=deps.active_context.entries[0].connection_id,
        kind=MailAccountKind.GOOGLE_WORKSPACE,
        now=datetime.now(UTC),
    )
    assert budget.used == 1


async def test_approval_needs_a_test_of_the_current_subject_body_and_fallbacks(
    approval: Approval, monkeypatch: pytest.MonkeyPatch
) -> None:
    deps = approval.deps
    definition = replace(
        DEFINITION, approval_review_action=partial(send_merge_test, approval.provider)
    )
    monkeypatch.setitem(RUNTIME_TOOL_CATALOG, definition.name, definition)

    async def authorised_context(*args: Any, **kwargs: Any) -> Any:
        return deps

    monkeypatch.setattr(
        "services.agents.runtime.entity_references.service.authorize_tool_context",
        authorised_context,
    )

    def leaf(display: dict[str, Any]) -> Any:
        return SimpleNamespace(
            call=SimpleNamespace(tool_name=definition.name), metadata={"display_args": display}
        )

    proposed = await describe_merge_approval(approval.provider, deps, ARGS)
    with pytest.raises(AppValidationError, match="Review the changed details"):
        validate_retained_review(leaf(proposed), ARGS)

    tested = await build_review_display_args(
        deps.db,
        actor=deps.user,
        workspace=deps.workspace,
        membership=approval.membership,
        run=deps.run,
        definition=definition,
        tool_call_id="call-1",
        canonical=ARGS,
    )
    validate_retained_review(leaf(tested), ARGS)
    edited = {**ARGS, "body_html": "<p>Hello {{first_name|there}}</p>"}
    with pytest.raises(AppValidationError, match="Review the changed details"):
        validate_retained_review(leaf(tested), edited)


async def test_running_the_same_approved_call_twice_records_one_merge_and_one_job(
    approval: Approval, monkeypatch: pytest.MonkeyPatch
) -> None:
    deps = approval.deps
    connection_id = str(deps.active_context.entries[0].connection_id)
    monkeypatch.setattr(
        create_module,
        "approved_display_args",
        lambda ctx: {"_mailbox": {"connection_id": connection_id}},
    )
    entry = deps.active_context.entries[0]

    async def one_mailbox(ctx: Any, *, binding: Any, provider_scope_id: str, operation: Any) -> Any:
        assert provider_scope_id == entry.external_id
        return [
            IntegrationContextResult(entry=entry, status="success", data=await operation(entry))
        ]

    monkeypatch.setattr(create_module, "run_context_scope", one_mailbox)
    ctx = SimpleNamespace(deps=deps, tool_call_id="call-1")
    args = MailMergeArgs.model_validate(
        {
            **ARGS,
            "recipients": [
                *ARGS["recipients"],
                {"email": "DANA@example.com", "first_name": "Dana"},
                {"email": "lee@example.com"},
            ],
        }
    )

    [first] = [
        entry["data"]
        for entry in (await create_mail_merge(approval.provider, ctx, args))["results"]
    ]
    [second] = [
        entry["data"]
        for entry in (await create_mail_merge(approval.provider, ctx, args))["results"]
    ]

    assert first["merge_id"] == second["merge_id"]
    assert (first["sending_to"], first["not_sent"]) == (2, 1)
    db = deps.db
    merges = select(func.count()).select_from(MailMerge).where(MailMerge.run_id == deps.run.id)
    assert await db.scalar(merges) == 1
    merge_id = first["merge_id"]
    statuses = (
        await db.execute(
            select(MailMergeRecipient.email, MailMergeRecipient.status)
            .where(MailMergeRecipient.merge_id == merge_id)
            .order_by(MailMergeRecipient.position)
        )
    ).all()
    assert statuses == [
        ("dana@example.com", "pending"),
        ("kai@example.com", "pending"),
        ("lee@example.com", "skipped"),
    ]
    jobs = await db.scalar(select(func.count()).select_from(Job).where(Job.subject_id == merge_id))
    assert jobs == 1
