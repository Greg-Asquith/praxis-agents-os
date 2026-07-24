# apps/api/tests/services/integrations/context/test_prompt_block.py

"""Active-context prompt rendering tests."""

from uuid import uuid4

from services.agents.runtime.prompt import PromptBlock, build_system_prompt, runtime_prompt_blocks
from services.integrations.context.domain import (
    ResolvedActiveContext,
    ResolvedContextEntry,
    UnavailableContextEntry,
)
from services.integrations.context.prompt_block import (
    ACTIVE_CONTEXT_LAW,
    render_active_context_block,
)


def _entry(name: str = "Account", **overrides) -> ResolvedContextEntry:
    values = {
        "integration_resource_id": uuid4(),
        "provider_key": "test_provider",
        "resource_type": "account",
        "external_id": "account-1",
        "display_name": name,
        "connection_id": uuid4(),
        "connection_label": "Agency",
        "connection_status": "degraded",
        "write_allowed": False,
    }
    values.update(overrides)
    return ResolvedContextEntry(**values)


def test_empty_context_renders_no_block() -> None:
    assert render_active_context_block(ResolvedActiveContext()) == ""


def test_prompt_renders_law_entries_and_unavailable_reasons() -> None:
    rendered = render_active_context_block(
        ResolvedActiveContext(
            source="conversation",
            selection_kind="context_group",
            group_name="Morning review",
            entries=(_entry(),),
            unavailable=(
                UnavailableContextEntry(
                    display_name="Old account",
                    provider_key="test_provider",
                    reason="connection_needs_reauth",
                ),
            ),
        )
    )

    assert rendered.index(ACTIVE_CONTEXT_LAW) < rendered.index("Account")
    assert 'Context group: "Morning review"' in rendered
    assert "degraded, read-only" in rendered
    assert "connection_needs_reauth" in rendered


def test_active_context_block_precedes_files_and_preserves_law_when_truncated() -> None:
    class AgentValue:
        instructions = "Identity"

    content = render_active_context_block(
        ResolvedActiveContext(entries=tuple(_entry(f"Account {index}") for index in range(100)))
    )
    blocks = runtime_prompt_blocks(
        AgentValue(),
        include_delegation=False,
        active_context_block=content,
    )

    assert [block.key for block in blocks] == [
        "identity",
        "active_context",
        "planning",
        "delegation",
        "available_files",
        "knowledge",
        "untrusted_content_policy",
    ]
    rendered = build_system_prompt([PromptBlock("context", content, budget=2000)])
    assert ACTIVE_CONTEXT_LAW in rendered
    assert rendered.endswith("[truncated]")
