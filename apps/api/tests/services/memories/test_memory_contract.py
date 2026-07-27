"""Registry schema and prompt-policy contracts."""

from uuid import uuid4

from models.agent import Agent
from services.agents.runtime.prompt import MEMORY_INSTRUCTIONS, runtime_prompt_blocks
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG, build_runtime_tools
from services.memories.domain import MEMORY_TOOL_NAMES


def _agent(tool_names: list[str]) -> Agent:
    return Agent(
        id=uuid4(),
        name="Memory Agent",
        slug="memory-agent",
        instructions="Reply plainly.",
        workspace_id=uuid4(),
        created_by=uuid4(),
        tool_names=tool_names,
    )


def test_registry_contains_exact_memory_tool_set() -> None:
    assert {name for name in RUNTIME_TOOL_CATALOG if "memory" in name} == MEMORY_TOOL_NAMES


def test_memory_schemas_do_not_expose_provenance() -> None:
    forbidden = {
        "conversation_id",
        "run_id",
        "user_id",
        "created_by",
        "created_by_user_id",
        "source",
    }
    for name in MEMORY_TOOL_NAMES:
        schema = RUNTIME_TOOL_CATALOG[name].serialized_input_schema()
        assert schema is not None
        assert forbidden.isdisjoint(schema["properties"])


def test_memory_policy_always_renders_for_auto_mounted_tools() -> None:
    blocks = runtime_prompt_blocks(_agent([]), include_delegation=False)
    assert (
        next(block for block in blocks if block.key == "memory_policy").content
        == MEMORY_INSTRUCTIONS
    )


def test_memory_tools_are_auto_mounted_and_use_expected_effects() -> None:
    assert RUNTIME_TOOL_CATALOG["search_memory"].effect == "read"
    for name in MEMORY_TOOL_NAMES:
        definition = RUNTIME_TOOL_CATALOG[name]
        assert definition.effect_scope == "internal"
        assert definition.auto_mount is True
        assert definition.configurable is False
        assert definition.supports_approval is True
    for name in ("save_memory", "update_memory", "forget_memory"):
        assert RUNTIME_TOOL_CATALOG[name].effect == "write"


def test_agent_without_saved_tool_names_receives_all_memory_tools() -> None:
    mounted_names = {tool.name for tool in build_runtime_tools(_agent([]))}
    assert MEMORY_TOOL_NAMES.issubset(mounted_names)
