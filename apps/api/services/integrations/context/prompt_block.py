# apps/api/services/integrations/context/prompt_block.py

"""Render active integration context for the runtime system prompt."""

from services.integrations.context.domain import ResolvedActiveContext
from services.integrations.manifest import PROVIDER_MANIFESTS

ACTIVE_CONTEXT_LAW = (
    "You are operating on the following active context. The listed resources are your "
    "authorization boundary; you cannot use different accounts, connections, or resources. "
    "Follow each integration tool's description for execution scope: some tools run once per "
    "compatible resource, while others perform one operation constrained to the listed resources."
)
UNSELECTED_CONVERSATION_LINE = (
    "{provider} is connected. Ask the user to select it in the context picker before using it."
)
UNSELECTED_SCHEDULE_LINE = (
    "{provider} is connected but not selected for this schedule. "
    "Say so in your result instead of guessing."
)


def render_active_context_block(resolved: ResolvedActiveContext) -> str:
    """Render the non-negotiable context law before its bounded listing."""
    unselected_lines = _unselected_provider_lines(resolved)
    if resolved.is_empty:
        return (
            "\n".join(["## Active Integrations", "", *unselected_lines]) if unselected_lines else ""
        )
    lines = ["## Active Integrations", "", ACTIVE_CONTEXT_LAW]
    if resolved.groups:
        label = "Context group" if len(resolved.groups) == 1 else "Context groups"
        names = ", ".join(f'"{name}"' for _group_id, name in resolved.groups)
        lines.extend(["", f"{label}: {names}"])
    if resolved.entries:
        lines.append("")
    for entry in resolved.entries:
        provider_label = _provider_label(entry.provider_key)
        markers = []
        if entry.connection_status == "degraded":
            markers.append("degraded")
        if not entry.write_allowed:
            markers.append("read-only")
        if entry.is_personal:
            markers.append("personal")
        suffix = f", {', '.join(markers)}" if markers else ""
        lines.append(
            f"- {entry.display_name} ({provider_label} {entry.resource_type}, "
            f'connection "{entry.connection_label}"{suffix})'
        )
    if resolved.unavailable:
        lines.extend(["", "Unavailable selections:", ""])
        lines.extend(
            f"- {entry.display_name} ({entry.provider_key}): {entry.reason}"
            for entry in resolved.unavailable
        )
    if unselected_lines:
        lines.extend(["", *unselected_lines])
    return "\n".join(lines)


def _unselected_provider_lines(resolved: ResolvedActiveContext) -> list[str]:
    template = (
        UNSELECTED_SCHEDULE_LINE if resolved.source == "schedule" else UNSELECTED_CONVERSATION_LINE
    )
    return [
        f"- {template.format(provider=_provider_label(provider_key))}"
        for provider_key in resolved.unselected_provider_keys
    ]


def _provider_label(provider_key: str) -> str:
    provider = PROVIDER_MANIFESTS.get(provider_key)
    return provider.display_name if provider is not None else provider_key
