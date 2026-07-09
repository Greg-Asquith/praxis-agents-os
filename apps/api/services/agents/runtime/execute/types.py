# apps/api/services/agents/runtime/execute/types.py

"""Shared private types for execute_run phase helpers."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic_ai.messages import ModelMessage, UserContent

from models.agent_run import AgentRun
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.loop import RuntimeAgent


@dataclass(frozen=True)
class ExecuteRunResult:
    """Result returned by the Praxis runtime core."""

    run: AgentRun
    output: Any
    new_message_count: int


@dataclass(frozen=True)
class BuiltRuntimeAgent:
    runtime_agent: RuntimeAgent
    history: list[ModelMessage]


@dataclass(frozen=True)
class PreparedRuntime:
    user_prompt: str | Sequence[UserContent] | None
    built_agent: BuiltRuntimeAgent
    deps: RuntimeDeps
