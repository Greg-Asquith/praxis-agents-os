# apps/api/services/integrations/context/domain.py

"""Pure active-context domain values shared by selection and runtime layers."""

from dataclasses import dataclass, field
from typing import Literal, Protocol
from uuid import UUID

SELECTION_TYPE_RESOURCE = "resource"
SELECTION_TYPE_CONTEXT_GROUP = "context_group"

UnavailableReason = Literal[
    "connection_needs_reauth",
    "connection_revoked",
    "connection_error",
    "connection_inactive",
    "resource_disabled",
    "resource_removed",
    "dangling",
]


class IntegrationBinding(Protocol):
    """Structural subset needed to match a runtime integration binding."""

    provider_keys: frozenset[str]
    resource_types: frozenset[str]


@dataclass(frozen=True)
class ResolvedContextEntry:
    integration_resource_id: UUID
    provider_key: str
    resource_type: str
    external_id: str
    display_name: str
    connection_id: UUID
    connection_label: str
    connection_status: str
    write_allowed: bool
    permissions_metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class UnavailableContextEntry:
    display_name: str
    provider_key: str
    reason: UnavailableReason


@dataclass(frozen=True)
class ResolvedActiveContext:
    source: Literal["conversation", "schedule"] | None = None
    selection_kind: Literal["resource", "context_group"] | None = None
    group_id: UUID | None = None
    group_name: str | None = None
    entries: tuple[ResolvedContextEntry, ...] = ()
    unavailable: tuple[UnavailableContextEntry, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.entries and not self.unavailable

    def compatible_entries(self, binding: IntegrationBinding) -> tuple[ResolvedContextEntry, ...]:
        return tuple(
            entry
            for entry in self.entries
            if entry.provider_key in binding.provider_keys
            and entry.resource_type in binding.resource_types
        )


EMPTY_ACTIVE_CONTEXT = ResolvedActiveContext()
