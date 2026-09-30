# apps/api/tests/services/agents/runtime/test_prompt_assembly.py

"""Tests for runtime system prompt assembly."""

from models.agent import Agent
from services.agents.builtin.identity import BUILTIN_AGENT_INSTRUCTIONS
from services.agents.runtime import prompt as prompt_module
from services.agents.runtime.prompt import (
    PromptBlock,
    build_system_prompt,
    runtime_prompt_blocks,
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


def test_builtin_identity_keeps_long_workspace_instructions_after_base() -> None:
    def prompt(agent: Agent) -> str:
        return build_system_prompt(runtime_prompt_blocks(agent, include_delegation=False))

    extra = "Reply in French. " * 1_176
    builtin_prompt = prompt(Agent(is_builtin=True, instructions=extra))

    assert builtin_prompt.startswith(BUILTIN_AGENT_INSTRUCTIONS)
    assert f"## Workspace instructions\n\n{extra.strip()}\n\n" in builtin_prompt
    assert "[truncated]" not in builtin_prompt
    assert prompt(Agent(is_builtin=False, instructions="Reply in French.")).startswith(
        "Reply in French.\n\n"
    )
