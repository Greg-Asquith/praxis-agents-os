# apps/api/services/agents/runtime/prompt.py

"""Assemble runtime system prompts from ordered blocks; future context slices append here."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from core.settings import settings
from models.agent import Agent
from services.agents.runtime.delegation.tool_names import (
    DELEGATE_TO_AGENT_TOOL_NAME,
    LIST_DELEGATE_AGENTS_TOOL_NAME,
)
from services.agents.runtime.load_context import AvailableFile

logger = logging.getLogger(__name__)

DELEGATION_INSTRUCTIONS = f"""\
You may delegate clearly bounded subtasks to other agents only when a listed
delegate is better suited than handling the work yourself.

Delegation rules:
- Call {LIST_DELEGATE_AGENTS_TOOL_NAME} before {DELEGATE_TO_AGENT_TOOL_NAME}.
- Use {DELEGATE_TO_AGENT_TOOL_NAME} only with an id returned by {LIST_DELEGATE_AGENTS_TOOL_NAME}.
- Give the delegate complete task instructions and relevant context.
- Treat the delegate result as supporting evidence; you remain responsible for
  the final answer to the user.
- If a delegated run needs approval, tell the user what is pending instead of
  retrying the same delegation.
"""

PLANNING_TOOL_NAME = "write_todos"
PLANNING_INSTRUCTIONS = """\
Use the conversation todo list for multi-step work. Keep it current by replacing
the list as priorities change, maintain exactly one in_progress item while
actively working, and clear the list when the task is complete.
"""


@dataclass(frozen=True)
class PromptBlock:
    """One ordered block in the runtime system prompt."""

    key: str
    content: str
    budget: int | None = None


def runtime_prompt_blocks(
    agent: Agent,
    *,
    include_delegation: bool,
    available_files: Sequence[AvailableFile] = (),
) -> list[PromptBlock]:
    """Return the canonical ordered prompt blocks for one runtime agent."""
    return [
        PromptBlock("identity", agent.instructions),
        PromptBlock(
            "planning",
            PLANNING_INSTRUCTIONS,
        ),
        PromptBlock(
            "delegation",
            DELEGATION_INSTRUCTIONS if include_delegation else "",
        ),
        PromptBlock(
            "available_files",
            _render_available_files(available_files),
            budget=settings.AVAILABLE_FILES_PROMPT_BUDGET,
        ),
    ]


def build_system_prompt(blocks: Sequence[PromptBlock]) -> str:
    """Join non-empty prompt blocks with blank-line separators."""
    rendered_blocks = [_render_block(block) for block in blocks if block.content]
    if len(rendered_blocks) <= 1:
        return rendered_blocks[0] if rendered_blocks else ""
    return "\n\n".join([*(block.rstrip() for block in rendered_blocks[:-1]), rendered_blocks[-1]])


def _render_block(block: PromptBlock) -> str:
    content = block.content
    if block.budget is not None and len(content) > block.budget:
        logger.warning(
            "Runtime prompt block exceeded its soft budget",
            extra={
                "prompt_block": block.key,
                "budget": block.budget,
                "length": len(content),
            },
        )
        return f"{content[: block.budget]}\n[truncated]"
    return content


def _render_available_files(files: Sequence[AvailableFile]) -> str:
    if not files:
        return ""
    instruction = "These workspace files are attached to this conversation. Use read_file with the id to read one."
    instruction += " Use list_files to see everything available."
    lines = [
        "<available_files>",
        instruction,
    ]
    lines.extend(
        (
            f"- {file.id} - {file.name} "
            f"({file.category}, {file.media_type}, {file.size_bytes} bytes, {file.processing_status})"
        )
        for file in files
    )
    lines.append("</available_files>")
    return "\n".join(lines)
