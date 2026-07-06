# apps/api/tests/services/agents/runtime/test_prompt_assembly.py

"""Tests for runtime system prompt assembly."""

from uuid import uuid4

from models.agent import Agent
from services.agents.runtime import prompt as prompt_module
from services.agents.runtime.load_context import AvailableFile
from services.agents.runtime.loop import _runtime_instructions
from services.agents.runtime.prompt import (
    DELEGATION_INSTRUCTIONS,
    PLANNING_INSTRUCTIONS,
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


def test_build_system_prompt_truncates_budgeted_blocks(monkeypatch) -> None:
    logs: list[str] = []

    def capture_log(message: str, **_kwargs: object) -> None:
        logs.append(message)

    monkeypatch.setattr(prompt_module.logger, "warning", capture_log)

    prompt = build_system_prompt([PromptBlock("long", "abcdef", budget=3)])

    assert prompt == "abc\n[truncated]"
    assert "Runtime prompt block exceeded its soft budget" in logs


def test_runtime_instructions_match_previous_concatenation() -> None:
    agent = _agent(instructions="Reply plainly.")

    assert (
        _runtime_instructions(agent, include_delegation=False)
        == f"Reply plainly.\n\n{PLANNING_INSTRUCTIONS}"
    )
    assert (
        _runtime_instructions(agent, include_delegation=True)
        == f"Reply plainly.\n\n{PLANNING_INSTRUCTIONS.rstrip()}\n\n{DELEGATION_INSTRUCTIONS}"
    )


def test_runtime_instructions_adds_planning_block_without_tool_config() -> None:
    agent = _agent(instructions="Reply plainly.", tool_names=[])

    assert (
        _runtime_instructions(agent, include_delegation=False)
        == f"Reply plainly.\n\n{PLANNING_INSTRUCTIONS}"
    )


def test_runtime_instructions_includes_available_files_block() -> None:
    agent = _agent(instructions="Reply plainly.", tool_names=[])
    file_id = uuid4()

    prompt = _runtime_instructions(
        agent,
        include_delegation=False,
        available_files=[
            AvailableFile(
                id=file_id,
                name="brief.md",
                category="editable_text",
                media_type="text/markdown",
                size_bytes=42,
                processing_status="ready",
            )
        ],
    )

    assert "<available_files>" in prompt
    assert str(file_id) in prompt
    assert "brief.md" in prompt
    assert "Use read_file with the id to read one" in prompt


def test_runtime_instructions_omits_available_files_when_none_are_attached() -> None:
    agent = _agent(instructions="Reply plainly.", tool_names=[])

    prompt = _runtime_instructions(
        agent,
        include_delegation=False,
        available_files=[],
    )

    assert "<available_files>" not in prompt


def _agent(*, instructions: str, tool_names: list[str] | None = None) -> Agent:
    return Agent(
        id=uuid4(),
        name="Runtime Agent",
        slug="runtime-agent",
        instructions=instructions,
        workspace_id=uuid4(),
        created_by=uuid4(),
        tool_names=tool_names or [],
    )
