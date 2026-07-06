# apps/api/services/agents/runtime/tools/planning.py

"""Conversation planning tools for runtime agents."""

from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import ModelRetry, RunContext
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.sql import func

from models.conversation_todos import ConversationTodoList
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import TOOL_EFFECT_WRITE, ToolPresentation
from services.agents.runtime.tools.registry import runtime_tool

TodoStatus = Literal["pending", "in_progress", "completed"]
MAX_TODO_ITEMS = 50


class TodoItemInput(BaseModel):
    """One item in the conversation planning scratchpad."""

    content: str = Field(min_length=1, max_length=500)
    status: TodoStatus


@runtime_tool(
    name="write_todos",
    provider="core",
    label="Write todo list",
    description=(
        "Replace the whole conversation todo list. Keep exactly one item in_progress "
        "while working and keep finished items in the list marked completed; pass an "
        "empty list only when the plan no longer applies."
    ),
    effect=TOOL_EFFECT_WRITE,
    supports_approval=False,
    takes_ctx=True,
    timeout=5,
    configurable=False,
    auto_mount=True,
    presentation=ToolPresentation(
        icon="list-todo",
        running_label="Updating the Plan",
        completed_label="Updated the Plan",
        failed_label="Couldn't Update the Plan",
    ),
)
async def write_todos(
    ctx: RunContext[RuntimeDeps],
    items: list[TodoItemInput],
) -> dict[str, object]:
    """Replace the current conversation todo list with the supplied items."""
    if len(items) > MAX_TODO_ITEMS:
        raise ModelRetry(f"Todo lists are limited to {MAX_TODO_ITEMS} items.")

    normalized = [item.model_dump(mode="json") for item in items]
    counts = _todo_counts(normalized)
    stmt = (
        insert(ConversationTodoList)
        .values(
            conversation_id=ctx.deps.conversation.id,
            workspace_id=ctx.deps.workspace.id,
            items=normalized,
            updated_by_run_id=ctx.deps.run.id,
        )
        .on_conflict_do_update(
            constraint="uq_conversation_todos_conversation_id",
            set_={
                "workspace_id": ctx.deps.workspace.id,
                "items": normalized,
                "updated_by_run_id": ctx.deps.run.id,
                "updated_at": func.now(),
                "deleted": False,
                "deleted_at": None,
                "deleted_by": None,
            },
        )
    )
    await ctx.deps.db.execute(stmt)
    await ctx.deps.db.flush()

    return {"items": normalized, "counts": counts}


@runtime_tool(
    name="read_todos",
    provider="core",
    label="Read todo list",
    description="Read the current conversation todo list.",
    supports_approval=False,
    takes_ctx=True,
    timeout=5,
    configurable=False,
    auto_mount=True,
    presentation=ToolPresentation(
        icon="list-todo",
        running_label="Checking the Plan",
        completed_label="Checked the Plan",
        failed_label="Couldn't Read the Plan",
    ),
)
async def read_todos(ctx: RunContext[RuntimeDeps]) -> dict[str, object]:
    """Return the current conversation todo list, or an empty list."""
    todo_list = await ctx.deps.db.scalar(
        select(ConversationTodoList).where(
            ConversationTodoList.conversation_id == ctx.deps.conversation.id,
            ConversationTodoList.workspace_id == ctx.deps.workspace.id,
            ConversationTodoList.deleted == False,  # noqa: E712
        )
    )
    items = list(todo_list.items) if todo_list is not None else []
    return {"items": items, "counts": _todo_counts(items)}


def _todo_counts(items: list[dict[str, object]]) -> dict[str, int]:
    counts = {"pending": 0, "in_progress": 0, "completed": 0}
    for item in items:
        status = item.get("status")
        if status in counts:
            counts[status] += 1
    return counts
