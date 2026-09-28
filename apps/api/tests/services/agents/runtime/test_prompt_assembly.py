# apps/api/tests/services/agents/runtime/test_prompt_assembly.py

"""Tests for runtime system prompt assembly."""

from services.agents.runtime import prompt as prompt_module
from services.agents.runtime.prompt import (
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
