# apps/api/services/agents/runtime/delegation/__init__.py

"""Runtime support for primary-agent delegation to allowed specialist agents."""

from services.agents.runtime.delegation.build_delegation_tools import (
    build_delegation_tools,
)
from services.agents.runtime.delegation.constants import (
    DELEGATE_NOT_ALLOWED_ERROR_CODE,
    DELEGATE_NOT_ALLOWED_ERROR_MESSAGE,
    DELEGATE_OUTPUT_PREVIEW_MAX_LENGTH,
    DELEGATE_TASK_MAX_LENGTH,
    DELEGATE_TASK_PREVIEW_MAX_LENGTH,
)
from services.agents.runtime.delegation.delegate_to_agent import delegate_to_agent
from services.agents.runtime.delegation.get_visible_delegate_agent import (
    get_visible_delegate_agent,
)
from services.agents.runtime.delegation.list_delegate_agents import list_delegate_agents
from services.agents.runtime.delegation.list_visible_delegate_agents import (
    list_visible_delegate_agents,
)
from services.agents.runtime.delegation.schemas import (
    DelegateAgentSummary,
    DelegateRunResult,
)

__all__ = [
    "DELEGATE_NOT_ALLOWED_ERROR_CODE",
    "DELEGATE_NOT_ALLOWED_ERROR_MESSAGE",
    "DELEGATE_OUTPUT_PREVIEW_MAX_LENGTH",
    "DELEGATE_TASK_MAX_LENGTH",
    "DELEGATE_TASK_PREVIEW_MAX_LENGTH",
    "DelegateAgentSummary",
    "DelegateRunResult",
    "build_delegation_tools",
    "delegate_to_agent",
    "get_visible_delegate_agent",
    "list_delegate_agents",
    "list_visible_delegate_agents",
]
