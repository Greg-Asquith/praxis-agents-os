# apps/api/tests/services/integrations/context/test_prompt_block.py

"""Active-context prompt rendering tests."""

from uuid import uuid4

from services.agents.runtime.prompt import PromptBlock, build_system_prompt, runtime_prompt_blocks
from services.integrations.context.domain import (
    ResolvedActiveContext,
    ResolvedContextEntry,
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


def test_active_context_block_precedes_files_and_preserves_law_when_truncated() -> None:
    class AgentValue:
        instructions = "Identity"
        is_builtin = False
        metadata_json = None

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
        "subagent",
        "conversation_context",
        "memory",
        "active_context",
        "planning",
        "approvals",
        "formatting",
        "delegation",
        "available_files",
        "skills",
        "knowledge",
        "memory_policy",
        "untrusted_content_policy",
        "completion_contract",
        "current_datetime",
    ]
    rendered = build_system_prompt([PromptBlock("context", content, budget=2000)])
    assert ACTIVE_CONTEXT_LAW in rendered
    assert rendered.endswith("[truncated]")


def test_active_context_block_names_each_mailbox_provider(monkeypatch) -> None:
    from services.integrations.context import prompt_block

    manifests = {
        key: type("Manifest", (), {"display_name": label})()
        for key, label in (("gmail", "Gmail"), ("outlook_mail", "Outlook Mail"))
    }
    monkeypatch.setattr(prompt_block, "PROVIDER_MANIFESTS", manifests)

    content = render_active_context_block(
        ResolvedActiveContext(
            entries=(
                _entry("a@example.com", provider_key="gmail", resource_type="gmail_mailbox"),
                _entry(
                    "b@example.com", provider_key="outlook_mail", resource_type="outlook_mailbox"
                ),
            )
        )
    )

    assert "- a@example.com (provider: Gmail, type: gmail_mailbox," in content
    assert "- b@example.com (provider: Outlook Mail, type: outlook_mailbox," in content
