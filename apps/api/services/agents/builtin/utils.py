# apps/api/services/agents/builtin/utils.py

"""Helpers specific to the built-in workspace agent."""

from services.agents.builtin.identity import BUILTIN_AGENT_INSTRUCTIONS

WORKSPACE_INSTRUCTIONS_HEADING = "## Workspace instructions"


def render_builtin_instructions(workspace_instructions: str | None) -> str:
    """Returns the base instructions followed by any workspace instructions."""
    extra = (workspace_instructions or "").strip()
    if not extra:
        return BUILTIN_AGENT_INSTRUCTIONS
    return f"{BUILTIN_AGENT_INSTRUCTIONS}\n{WORKSPACE_INSTRUCTIONS_HEADING}\n\n{extra}"
