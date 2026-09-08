"""Fences late finalisers after a separately committed continuation claim."""

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic_ai import DeferredToolRequests
from pydantic_ai.usage import RunUsage
from sqlalchemy import select

from models.agent_run import AgentRun
from models.ai_usage_event import AIUsageEvent
from models.conversation import Conversation, ConversationMessage
from services.agent_runs import (
    complete_agent_run,
    mark_run_awaiting_approval,
    start_agent_run_with_lease,
)
from services.agent_runs.claim_execution import claim_agent_run_execution
from services.agents.runtime.execute.finalize import finalize_successful_run
from services.agents.runtime.run_persistence import (
    persist_cancelled_run,
    persist_failed_run,
    persist_suspended_run,
)
from services.agents.runtime.sinks import CollectingSink
from services.ai_usage.agent_run_accounting import AgentRunMeteringContext
from services.ai_usage.utils import usage_values
from tests.support.scenario import build_scenario_agent


@pytest.mark.parametrize("replacement_status", ["running", "completed", "awaiting_approval"])
@pytest.mark.parametrize("attempt", ["success", "suspension", "failure", "cancellation"])
async def test_old_invocation_cannot_settle_replacement(
    committed_db_session_factory, replacement_status, attempt
):
    context = await build_scenario_agent(committed_db_session_factory)
    old_owner, new_owner = str(uuid4()), str(uuid4())
    usage = RunUsage(requests=1, input_tokens=11, output_tokens=3)
    async with committed_db_session_factory() as db:
        run = await db.get(AgentRun, context.run_id)
        await start_agent_run_with_lease(db, run, owner_instance_id=old_owner)
        metering = AgentRunMeteringContext(
            baseline=usage_values(RunUsage()),
            usage=usage,
            provider="openai",
            model="gpt-5.4-mini",
            invocation_id=UUID(old_owner),
        )
        metering.capture_run(run)
        await mark_run_awaiting_approval(db, run)
        await db.commit()
    async with committed_db_session_factory() as db:
        run = await db.get(AgentRun, context.run_id)
        await claim_agent_run_execution(db, run, owner_instance_id=new_owner)
        run.metadata_json = {"continuation": "replacement"}
        run.requests = 42
        if replacement_status == "completed":
            await complete_agent_run(db, run)
        elif replacement_status == "awaiting_approval":
            await mark_run_awaiting_approval(db, run)
        await db.commit()
        expected = (
            run.status,
            run.owner_instance_id,
            run.requests,
            run.metadata_json,
            run.completion_json,
        )
    terminal = SimpleNamespace(
        output="Late output", usage=usage, new_messages=list, all_messages=list
    )
    sink = CollectingSink(run_id=context.run_id, conversation_id=context.conversation_id)
    async with committed_db_session_factory() as db:
        if attempt == "success":
            result = await finalize_successful_run(
                db,
                event_sink=sink,
                conversation=await db.get(Conversation, context.conversation_id),
                run=await db.get(AgentRun, context.run_id),
                terminal_result=terminal,
                client_message_id=None,
                history=[],
                deferred_tool_results=None,
                usage_event=metering.event(),
            )
            assert result.output is None
        elif attempt == "suspension":
            _run, count, approvals = await persist_suspended_run(
                db,
                conversation_id=context.conversation_id,
                run_id=context.run_id,
                terminal_result=terminal,
                deferred_tool_requests=DeferredToolRequests(),
                client_message_id=None,
                usage_event=metering.event(),
            )
            assert count == 0 and approvals is None
        elif attempt == "failure":
            await persist_failed_run(
                db,
                run_id=context.run_id,
                error_code="old_failure",
                error_message="Old failure",
                owner_instance_id=old_owner,
                metering=metering,
            )
        else:
            await persist_cancelled_run(
                context.run_id,
                workspace_id=context.workspace_id,
                user_id=context.user_id,
                owner_instance_id=old_owner,
                metering=metering,
            )
    async with committed_db_session_factory() as db:
        run = await db.get(AgentRun, context.run_id)
        assert (
            run.status,
            run.owner_instance_id,
            run.requests,
            run.metadata_json,
            run.completion_json,
        ) == expected
        assert not list(
            await db.scalars(
                select(ConversationMessage).where(
                    ConversationMessage.conversation_id == context.conversation_id
                )
            )
        )
        [event] = list(
            await db.scalars(select(AIUsageEvent).where(AIUsageEvent.run_id == context.run_id))
        )
        assert event.requests == 1 and event.input_tokens == 11 and event.output_tokens == 3
