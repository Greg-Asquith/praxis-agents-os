# apps/api/services/tools/domain.py

"""Workspace tool defaults consumed by the runtime and tool routes."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from services.agents.runtime.tools.contract import ToolPolicy


@dataclass(frozen=True)
class WorkspaceToolDefaults:
    """One workspace's disabled tools and default approval policies."""

    disabled: frozenset[str] = frozenset()
    policies: Mapping[str, ToolPolicy] = field(default_factory=lambda: MappingProxyType({}))


EMPTY_WORKSPACE_TOOL_DEFAULTS = WorkspaceToolDefaults()
