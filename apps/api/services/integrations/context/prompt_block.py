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


def render_active_context_block(resolved: ResolvedActiveContext) -> str:
    """Render the non-negotiable context law before its bounded listing."""
    if resolved.is_empty:
        return ""
    lines = ["## Active Integrations", "", ACTIVE_CONTEXT_LAW]
    if resolved.group_name:
        lines.extend(["", f'Context group: "{resolved.group_name}"'])
    if resolved.entries:
        lines.append("")
    for entry in resolved.entries:
        provider = PROVIDER_MANIFESTS.get(entry.provider_key)
        provider_label = provider.display_name if provider is not None else entry.provider_key
        markers = []
        if entry.connection_status == "degraded":
            markers.append("degraded")
        if not entry.write_allowed:
            markers.append("read-only")
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
    return "\n".join(lines)
