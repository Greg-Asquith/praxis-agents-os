# apps/api/services/agents/runtime/tools/contract.py

"""Runtime tool catalog value types."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic_ai import Tool

from services.agents.models.domain import ModelConfigurationError
from services.agents.runtime.context import RuntimeDeps

ToolPolicy = Literal["auto", "approval"]

TOOL_POLICY_AUTO: ToolPolicy = "auto"
TOOL_POLICY_APPROVAL: ToolPolicy = "approval"
VALID_TOOL_POLICIES = frozenset({TOOL_POLICY_AUTO, TOOL_POLICY_APPROVAL})


@dataclass(frozen=True)
class RuntimeToolDefinition:
    """One Python-owned tool available for agent configuration."""

    name: str
    function: Callable[..., Any]
    description: str
    takes_ctx: bool = False
    default_policy: ToolPolicy = TOOL_POLICY_AUTO
    timeout: float | None = None
    max_retries: int | None = None
    args_validator: Callable[..., Any] | None = None
    defer_loading: bool = False

    def to_pydantic_tool(self, *, policy: ToolPolicy | None = None) -> Tool[RuntimeDeps]:
        """Build the Pydantic AI tool instance for one turn."""
        resolved_policy = policy or self.default_policy
        if resolved_policy not in VALID_TOOL_POLICIES:
            raise ModelConfigurationError(
                "Unknown runtime tool policy",
                details={
                    "tool_name": self.name,
                    "tool_policy": resolved_policy,
                    "valid_tool_policies": sorted(VALID_TOOL_POLICIES),
                },
            )

        return Tool(
            self.function,
            takes_ctx=self.takes_ctx,
            name=self.name,
            description=self.description,
            max_retries=self.max_retries,
            requires_approval=resolved_policy == TOOL_POLICY_APPROVAL,
            args_validator=self.args_validator,
            timeout=self.timeout,
            defer_loading=self.defer_loading,
        )
