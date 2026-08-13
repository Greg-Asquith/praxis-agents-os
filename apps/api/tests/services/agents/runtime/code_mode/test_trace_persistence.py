"""Persistence contract for settled code-mode nested traces."""

from types import SimpleNamespace
from uuid import uuid4

from pydantic_ai import RunContext, Tool
from pydantic_ai.messages import ModelRequest, ToolReturnPart
from pydantic_ai.models.test import TestModel
from pydantic_ai.tool_manager import ToolManager
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.usage import RunUsage
from sqlalchemy.ext.asyncio import AsyncSession

from models.conversation import Conversation
from services.agents.runtime.code_mode.bridge import (
    CODE_MODE_TRACE_METADATA_KEY,
    CodeModeBridge,
)
from services.agents.runtime.code_mode.executor import ScriptExecution
from services.agents.runtime.persistence import load_message_history, persist_new_messages
from services.agents.runtime.sinks import CollectingSink
from tests.factories import build_user, build_workspace, build_workspace_membership


async def test_settled_nested_trace_round_trips_through_conversation_reload(
    db_session: AsyncSession,
) -> None:
    conversation = await _conversation(db_session)
    run_id = uuid4()
    sink = CollectingSink(run_id=run_id, conversation_id=conversation.id)

    async def lookup(*, query: str) -> dict[str, str]:
        return {"query": query, "result": "found"}

    toolset = FunctionToolset([Tool(lookup)])
    ctx = RunContext(
        deps=SimpleNamespace(sink=sink),
        model=TestModel(),
        usage=RunUsage(),
    )
    ctx.tool_manager = ToolManager(toolset=toolset, ctx=ctx, tools={})
    bridge = await CodeModeBridge.create(
        ctx=ctx,
        wrapped_toolset=toolset,
        outer_tool_call_id="workflow-call",
    )
    await bridge.external_lookup()["lookup"](query="status")
    tool_return = bridge.finalize(ScriptExecution(result="done", output="", output_truncated=False))
    message = ModelRequest(
        parts=[
            ToolReturnPart(
                tool_name="run_workflow",
                tool_call_id="workflow-call",
                content=tool_return.return_value,
                metadata=tool_return.metadata,
            )
        ]
    )

    await persist_new_messages(
        db_session,
        conversation=conversation,
        run_id=run_id,
        messages=[message],
    )
    reloaded = await load_message_history(db_session, conversation_id=conversation.id)

    [reloaded_message] = reloaded
    [reloaded_part] = reloaded_message.parts
    assert isinstance(reloaded_part, ToolReturnPart)
    assert reloaded_part.metadata == tool_return.metadata
    [trace_entry] = reloaded_part.metadata[CODE_MODE_TRACE_METADATA_KEY]["calls"]
    assert trace_entry["parent_tool_call_id"] == "workflow-call"
    assert trace_entry["status"] == "succeeded"


async def _conversation(db: AsyncSession) -> Conversation:
    user = build_user(email=f"code-mode-trace-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"code-mode-trace-{uuid4().hex[:8]}")
    membership = build_workspace_membership(workspace_id=workspace.id, user_id=user.id)
    conversation = Conversation(
        user_id=user.id,
        workspace_id=workspace.id,
        created_by=user.id,
    )
    db.add_all([user, workspace, membership, conversation])
    await db.flush()
    return conversation
