# apps/api/services/integrations/plugin.py

"""Provider contribution contract used by the settings-driven loader."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from services.integrations.manifest import IntegrationProviderManifest

if TYPE_CHECKING:
    from services.agents.runtime.tools.contract import RuntimeToolDefinition

DiscoverResourcesFn = Callable[..., Awaitable[Any]]


@dataclass(frozen=True)
class IntegrationProviderPlugin:
    manifest: IntegrationProviderManifest
    discover_resources: DiscoverResourcesFn | None
    tool_definitions: tuple["RuntimeToolDefinition", ...] = ()
