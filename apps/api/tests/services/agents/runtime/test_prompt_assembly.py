# apps/api/tests/services/agents/runtime/test_prompt_assembly.py

"""Tests for runtime system prompt assembly."""

from uuid import uuid4

from models.agent import Agent
from services.agents.runtime.loop import _runtime_instructions
from services.agents.runtime.prompt import (
    DELEGATION_INSTRUCTIONS,
    PromptBlock,
    build_system_prompt,
)


def test_build_system_prompt_respects_order_and_omits_empty_blocks() -> None:
    assert (
        build_system_prompt(
            [
                PromptBlock("identity", "First block"),
                PromptBlock("empty", ""),
                PromptBlock("context", "Second block"),
            ]
        )
        == "First block\n\nSecond block"
    )


def test_build_system_prompt_truncates_budgeted_blocks(caplog) -> None:
    prompt = build_system_prompt([PromptBlock("long", "abcdef", budget=3)])

    assert prompt == "abc\n[truncated]"
    assert "Runtime prompt block exceeded its soft budget" in caplog.text


def test_runtime_instructions_match_previous_concatenation() -> None:
    agent = _agent(instructions="Reply plainly.")

    assert _runtime_instructions(agent, include_delegation=False) == "Reply plainly."
    assert (
        _runtime_instructions(agent, include_delegation=True)
        == f"Reply plainly.\n\n{DELEGATION_INSTRUCTIONS}"
    )


def _agent(*, instructions: str) -> Agent:
    return Agent(
        id=uuid4(),
        name="Runtime Agent",
        slug="runtime-agent",
        instructions=instructions,
        workspace_id=uuid4(),
        created_by=uuid4(),
    )
