# apps/api/services/agents/runtime/subagents/definition.py

"""The runtime-owned run_subagent tool definition."""

from services.agents.runtime.subagents.constants import RUN_SUBAGENT_TOOL_NAME
from services.agents.runtime.subagents.run_subagent import run_subagent
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    RuntimeToolDefinition,
    ToolFieldPresentation,
    ToolPresentation,
    validate_definition,
)

RUN_SUBAGENT_DEFINITION = RuntimeToolDefinition(
    name=RUN_SUBAGENT_TOOL_NAME,
    defer_loading=False,
    function=run_subagent,
    description=(
        "Hand one self-contained, token-heavy task to a throwaway sub-agent you define, "
        "and receive only its final answer. The sub-agent has your tools, except "
        "delegation, sub-agents, and memory changes, and cannot see this conversation. "
        "Use it for large reads, broad searches, or multi-step research whose "
        "intermediate data you do not need. Do not use it for a single tool call or for "
        "work that needs the user. Sub-agents run one at a time."
    ),
    label="Run Sub Agent",
    code_eligible=False,
    # Spawning has no external effect; each nested call keeps its own policy and approval.
    effect=TOOL_EFFECT_READ,
    takes_ctx=True,
    supports_approval=False,
    timeout=None,
    configurable=False,
    presentation=ToolPresentation(
        icon="bot",
        running_label="Running a Sub Agent",
        completed_label="Sub Agent Completed Task",
        failed_label="Sub Agent Couldn't Complete Task",
        arg_fields=(
            ToolFieldPresentation(key="role", label="Role"),
            ToolFieldPresentation(key="task", label="Task", format="multiline"),
        ),
        result_fields=(ToolFieldPresentation(key="output", label="Result", format="multiline"),),
    ),
)

validate_definition(RUN_SUBAGENT_DEFINITION)
