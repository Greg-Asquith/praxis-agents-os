# apps/api/tests/services/agents/runtime/test_native_tools.py

"""Tests for provider-native runtime tool catalog entries."""

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from pydantic_ai import ModelRetry
from pydantic_ai.messages import (
    ModelResponse,
    NativeToolCallPart,
    NativeToolReturnPart,
    PartStartEvent,
    TextPart,
)
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.settings import settings
from models.agent import Agent
from models.agent_run import AgentRun
from models.audit_event import AuditEvent
from models.conversation import Conversation, ConversationMessage
from models.user import User
from models.workspace import Workspace
from services.agent_runs import create_agent_run
from services.agents.models.domain import (
    PROVIDER_ANTHROPIC,
    PROVIDER_AZURE,
    PROVIDER_GOOGLE,
    PROVIDER_OPENAI,
    ResolvedModel,
)
from services.agents.models.utils import has_provider_api_key
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.dispatch import (
    digest_args,
    record_native_tool_invocation_audit_event,
)
from services.agents.runtime.envelope import RunEnvelope
from services.agents.runtime.events import (
    EVENT_TOOL_CALL,
    EVENT_TOOL_RESULT,
    EventTranslationState,
    emit_agent_stream_event,
)
from services.agents.runtime.sinks import CollectingSink
from services.agents.runtime.tools.native import web_search as web_search_tools
from services.agents.runtime.tools.registry import (
    RUNTIME_TOOL_CATALOG,
    build_runtime_native_capabilities,
    build_runtime_tools,
    list_allowed_tool_definitions,
)
from services.agents.runtime.tools.schemas import ToolCatalogEntry
from services.agents.utils import validate_tool_configuration
from tests.factories import build_user, build_workspace


@dataclass(frozen=True)
class NativeRuntimeContext:
    user_id: UUID
    workspace_id: UUID
    agent_id: UUID
    conversation_id: UUID
    run_id: UUID


def _agent(
    *,
    tool_names: list[str],
    model_provider: str = PROVIDER_OPENAI,
    model: str = "gpt-5.4-mini",
) -> Agent:
    return Agent(
        name="Native Tool Agent",
        slug=f"native-tool-agent-{uuid4().hex[:8]}",
        instructions="Use configured tools.",
        workspace_id=uuid4(),
        created_by=uuid4(),
        tool_names=tool_names,
        model_provider=model_provider,
        model=model,
    )


def _set_native_provider_keys(
    monkeypatch: pytest.MonkeyPatch,
    *,
    anthropic: str | None = None,
    google: str | None = None,
    openai: str | None = None,
    azure: str | None = None,
) -> None:
    for setting_name, value in (
        ("ANTHROPIC_API_KEY", anthropic),
        ("GOOGLE_API_KEY", google),
        ("OPENAI_API_KEY", openai),
        ("AZURE_OPENAI_API_KEY", azure),
    ):
        monkeypatch.setattr(
            settings,
            setting_name,
            SecretStr(value) if value is not None else None,
        )


@pytest.mark.parametrize(
    ("keys", "expected"),
    [
        ({}, ()),
        ({"anthropic": "sk-ant-test", "azure": "azure-test"}, ("anthropic",)),
        (
            {
                "anthropic": "sk-ant-test",
                "google": "google-test",
                "openai": "sk-openai-test",
                "azure": "azure-test",
            },
            ("anthropic", "google", "openai"),
        ),
    ],
)
def test_configured_native_search_providers(
    monkeypatch: pytest.MonkeyPatch,
    keys: dict[str, str],
    expected: tuple[str, ...],
) -> None:
    _set_native_provider_keys(monkeypatch, **keys)

    assert web_search_tools.configured_native_search_providers() == expected
    assert has_provider_api_key(PROVIDER_AZURE) is ("azure" in keys)


def test_web_search_catalog_entry_is_native_function_tool() -> None:
    definition = RUNTIME_TOOL_CATALOG["web_search"]
    entry = ToolCatalogEntry.from_definition(definition)

    assert entry.name == "web_search"
    assert entry.provider == "native"
    assert entry.kind == "function"
    assert entry.effect == "read"
    assert entry.effect_scope == "internal"
    assert entry.default_policy == "approval"
    assert entry.supported_policies == ["approval", "auto"]
    assert entry.provider_keys is None
    assert entry.resource_types is None
    assert definition.supports_approval is True
    assert definition.output_model is web_search_tools.WebSearchOutput
    assert definition.presentation.arg_fields[1].options == (
        "anthropic",
        "google",
        "openai",
    )

    assert validate_tool_configuration(
        tool_names=["web_search"],
        tool_policies={"web_search": "approval"},
    ) == {"web_search": "approval"}


def test_web_search_mounts_as_function_tool_and_todos_are_always_active() -> None:
    agent = _agent(tool_names=["web_search", "test_add_numbers"])
    resolved_model = ResolvedModel(
        provider=PROVIDER_OPENAI,
        model="gpt-5.4-mini",
        settings={},
        max_steps=10,
    )

    capabilities = build_runtime_native_capabilities(agent, resolved_model)
    tools = build_runtime_tools(agent)

    assert capabilities == []
    assert [tool.name for tool in tools] == [
        "build_chart",
        "forget_memory",
        "list_files",
        "read_document",
        "read_file",
        "read_todos",
        "save_memory",
        "search_knowledge",
        "search_memory",
        "update_memory",
        "write_file",
        "write_todos",
        "web_search",
        "test_add_numbers",
    ]
    web_search_tool = next(tool for tool in tools if tool.name == "web_search")
    schema = web_search_tool.function_schema.json_schema
    assert schema["required"] == ["query"]
    assert schema["properties"]["model_provider"] == {
        "anyOf": [
            {
                "enum": ["anthropic", "google", "openai"],
                "type": "string",
            },
            {"type": "null"},
        ],
        "default": None,
        "description": (
            "Optional helper model provider. Omit unless there is a reason to choose one. "
            "Available providers are anthropic, google, and openai."
        ),
    }


def test_web_search_availability_follows_configured_provider_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(tool_names=["web_search"])
    _set_native_provider_keys(monkeypatch)

    assert "web_search" not in {
        definition.name for definition in list_allowed_tool_definitions(workspace=object())
    }
    assert "web_search" not in {tool.name for tool in build_runtime_tools(agent)}

    _set_native_provider_keys(monkeypatch, google="google-test")

    assert "web_search" in {
        definition.name for definition in list_allowed_tool_definitions(workspace=object())
    }
    assert "web_search" in {tool.name for tool in build_runtime_tools(agent)}


def test_web_search_helper_model_can_differ_from_active_agent_model() -> None:
    agent = _agent(tool_names=["web_search"])

    model_spec = web_search_tools.resolve_web_search_model(
        agent,
        model_provider=PROVIDER_ANTHROPIC,
        model="claude-sonnet-4-6",
    )

    assert agent.model_provider == PROVIDER_OPENAI
    assert model_spec.provider == PROVIDER_ANTHROPIC
    assert model_spec.model == "claude-sonnet-4-6"


def test_web_search_rejects_unconfigured_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(tool_names=["web_search"])
    _set_native_provider_keys(monkeypatch, anthropic="sk-ant-test")

    with pytest.raises(
        ModelRetry,
        match=r"Provider 'google' is not configured.*Available configured providers: anthropic",
    ):
        web_search_tools.resolve_web_search_model(
            agent,
            model_provider=PROVIDER_GOOGLE,
            model=None,
        )


def test_web_search_rejects_unsupported_provider_with_configured_choices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(tool_names=["web_search"])
    _set_native_provider_keys(monkeypatch, anthropic="sk-ant-test")

    with pytest.raises(
        ModelRetry,
        match=r"Provider 'azure' is not configured.*Available configured providers: anthropic",
    ):
        web_search_tools.resolve_web_search_model(
            agent,
            model_provider=PROVIDER_AZURE,
            model=None,
        )


def test_web_search_omitted_provider_reuses_configured_agent_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(tool_names=["web_search"])
    _set_native_provider_keys(monkeypatch, openai="sk-openai-test")

    model_spec = web_search_tools.resolve_web_search_model(agent)

    assert model_spec.provider == PROVIDER_OPENAI
    assert model_spec.model == "gpt-5.4-mini"
    assert model_spec.max_steps == settings.NATIVE_WEB_SEARCH_MAX_STEPS


def test_web_search_omitted_provider_falls_back_to_first_configured_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(
        tool_names=["web_search"],
        model_provider=PROVIDER_AZURE,
        model="customer-deployment",
    )
    _set_native_provider_keys(
        monkeypatch,
        google="google-test",
        openai="sk-openai-test",
        azure="azure-test",
    )

    model_spec = web_search_tools.resolve_web_search_model(agent)

    assert model_spec.provider == PROVIDER_GOOGLE
    assert model_spec.model == web_search_tools.DEFAULT_NATIVE_SEARCH_MODELS[PROVIDER_GOOGLE]


def test_web_search_omitted_provider_uses_only_configured_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(tool_names=["web_search"])
    _set_native_provider_keys(monkeypatch, anthropic="sk-ant-test")

    model_spec = web_search_tools.resolve_web_search_model(agent)

    assert model_spec.provider == PROVIDER_ANTHROPIC
    assert model_spec.model == web_search_tools.DEFAULT_NATIVE_SEARCH_MODELS[PROVIDER_ANTHROPIC]


def test_web_search_omitted_provider_rejects_when_none_are_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(tool_names=["web_search"])
    _set_native_provider_keys(monkeypatch)

    with pytest.raises(ModelRetry, match="No native web_search providers are configured"):
        web_search_tools.resolve_web_search_model(agent)


@pytest.mark.asyncio
async def test_web_search_tool_uses_configured_helper_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(tool_names=["web_search"])
    captured: dict[str, object] = {}

    async def fake_search(
        *, query: str, model_spec: ResolvedModel
    ) -> web_search_tools.NativeWebSearchResult:
        captured["query"] = query
        captured["model_spec"] = model_spec
        return web_search_tools.NativeWebSearchResult(
            answer="searched answer",
            sources=[
                web_search_tools.WebSearchSource(
                    title="Praxis documentation",
                    url="https://docs.example.com/praxis",
                )
            ],
        )

    monkeypatch.setattr(web_search_tools, "run_native_web_search", fake_search)

    @dataclass
    class FakeDeps:
        agent: Agent

    class FakeContext:
        deps = FakeDeps(agent=agent)

    result = await web_search_tools.web_search(
        FakeContext(),
        " latest docs ",
        model_provider=PROVIDER_ANTHROPIC,
        model="claude-sonnet-4-6",
    )
    model_spec = captured["model_spec"]

    assert captured["query"] == "latest docs"
    assert isinstance(model_spec, ResolvedModel)
    assert model_spec.provider == PROVIDER_ANTHROPIC
    assert result == {
        "query": "latest docs",
        "answer": "searched answer",
        "sources": [
            {
                "title": "Praxis documentation",
                "url": "https://docs.example.com/praxis",
            }
        ],
        "model_provider": PROVIDER_ANTHROPIC,
        "model": "claude-sonnet-4-6",
    }


def test_web_search_extracts_only_structured_provider_sources() -> None:
    messages = [
        ModelResponse(
            parts=[
                NativeToolReturnPart(
                    content=[
                        {
                            "type": "web_search_result",
                            "title": "Anthropic source",
                            "url": "https://anthropic.example/source",
                        },
                        {
                            "title": "Unsafe source",
                            "url": "javascript:alert(1)",
                        },
                    ],
                    provider_name="anthropic",
                    tool_call_id="search-1",
                    tool_name="web_search",
                ),
                NativeToolReturnPart(
                    content=[
                        {
                            "domain": "google.example",
                            "title": "Google source",
                            "uri": "https://google.example/source",
                        }
                    ],
                    provider_name="google",
                    tool_call_id="search-2",
                    tool_name="web_search",
                ),
                NativeToolReturnPart(
                    content={
                        "sources": [
                            {
                                "type": "url",
                                "url": "https://openai.example/source",
                            }
                        ],
                        "status": "completed",
                    },
                    provider_name="openai",
                    tool_call_id="search-3",
                    tool_name="web_search",
                ),
                TextPart(
                    content="Answer with a citation.",
                    provider_details={
                        "annotations": [
                            {
                                "type": "url_citation",
                                "title": "OpenAI source",
                                "url": "https://openai.example/source",
                            },
                            {
                                "type": "url_citation",
                                "title": "Duplicate",
                                "url": "https://anthropic.example/source",
                            },
                        ]
                    },
                    provider_name="openai",
                ),
            ]
        )
    ]

    assert web_search_tools._web_search_sources(messages) == [
        web_search_tools.WebSearchSource(
            title="Anthropic source",
            url="https://anthropic.example/source",
        ),
        web_search_tools.WebSearchSource(
            title="Google source",
            url="https://google.example/source",
        ),
        web_search_tools.WebSearchSource(
            title="OpenAI source",
            url="https://openai.example/source",
        ),
    ]


@pytest.mark.asyncio
async def test_native_tool_parts_translate_to_tool_events() -> None:
    run_id = uuid4()
    sink = CollectingSink(run_id=run_id, conversation_id=uuid4())
    state = EventTranslationState()

    await emit_agent_stream_event(
        sink,
        PartStartEvent(
            index=0,
            part=NativeToolCallPart(
                tool_name="web_search",
                tool_call_id="native-search-call",
                args={"query": "latest docs"},
            ),
        ),
        run_id=str(run_id),
        state=state,
    )
    await emit_agent_stream_event(
        sink,
        PartStartEvent(
            index=1,
            part=NativeToolReturnPart(
                tool_name="web_search",
                tool_call_id="native-search-call",
                content={"status": "completed"},
            ),
        ),
        run_id=str(run_id),
        state=state,
    )

    assert [event.event for event in sink.events] == [EVENT_TOOL_CALL, EVENT_TOOL_RESULT]
    assert sink.events[0].data["name"] == "web_search"
    assert sink.events[0].data["args"] == {"query": "latest docs"}
    assert sink.events[1].data["result"] == {"status": "completed"}


@pytest.mark.asyncio
async def test_native_tool_audit_uses_digest_only(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await _create_committed_native_context(committed_db_session_factory)
    marker = f"native-secret-{uuid4().hex}"

    try:
        async with committed_db_session_factory() as db:
            deps = await _runtime_deps_for_context(db, context)
            await record_native_tool_invocation_audit_event(
                deps=deps,
                call_part=NativeToolCallPart(
                    tool_name="web_search",
                    tool_call_id="native-search-call",
                    args={"query": marker},
                ),
                return_part=NativeToolReturnPart(
                    tool_name="web_search",
                    tool_call_id="native-search-call",
                    content={"status": "completed"},
                ),
            )

        [event] = await _tool_audit_events(committed_db_session_factory, context)
        expected_sha, expected_bytes = digest_args({"query": marker})
        assert event.tool_name == "web_search"
        assert event.tool_provider == "native"
        assert event.status == "success"
        assert event.details["outcome"] == "completed"
        assert event.details["latency_ms"] is None
        assert event.details["args_sha256"] == expected_sha
        assert event.details["args_bytes"] == expected_bytes
        assert "args" not in event.details
        assert marker not in str(event.details)
    finally:
        await _delete_committed_native_context(committed_db_session_factory, context)


async def _create_committed_native_context(
    session_factory: async_sessionmaker[AsyncSession],
) -> NativeRuntimeContext:
    async with session_factory() as db:
        user = build_user(email=f"native-runtime-{uuid4().hex}@example.com")
        workspace = build_workspace(slug=f"native-runtime-{uuid4().hex[:8]}")
        db.add_all([user, workspace])
        await db.flush()

        agent = Agent(
            name="Native Runtime Agent",
            slug=f"native-runtime-agent-{uuid4().hex[:8]}",
            instructions="Reply plainly.",
            workspace_id=workspace.id,
            created_by=user.id,
            model_provider=PROVIDER_OPENAI,
            model="gpt-5.4-mini",
            tool_names=["web_search"],
        )
        db.add(agent)
        await db.flush()

        conversation = Conversation(
            user_id=user.id,
            workspace_id=workspace.id,
            created_by=user.id,
            active_agent_id=agent.id,
        )
        db.add(conversation)
        await db.flush()

        run = await create_agent_run(
            db,
            conversation_id=conversation.id,
            agent_id=agent.id,
            workspace_id=workspace.id,
            user_id=user.id,
            trigger="interactive",
        )
        await db.commit()

    return NativeRuntimeContext(
        user_id=user.id,
        workspace_id=workspace.id,
        agent_id=agent.id,
        conversation_id=conversation.id,
        run_id=run.id,
    )


async def _runtime_deps_for_context(
    db: AsyncSession,
    context: NativeRuntimeContext,
) -> RuntimeDeps:
    user = await db.get_one(User, context.user_id)
    workspace = await db.get_one(Workspace, context.workspace_id)
    agent = await db.get_one(Agent, context.agent_id)
    conversation = await db.get_one(Conversation, context.conversation_id)
    run = await db.get_one(AgentRun, context.run_id)
    return RuntimeDeps(
        db=db,
        user=user,
        workspace=workspace,
        conversation=conversation,
        agent=agent,
        run=run,
        sink=CollectingSink(
            run_id=context.run_id,
            conversation_id=context.conversation_id,
        ),
        envelope=RunEnvelope(principal="interactive"),
    )


async def _tool_audit_events(
    session_factory: async_sessionmaker[AsyncSession],
    context: NativeRuntimeContext,
) -> list[AuditEvent]:
    async with session_factory() as db:
        return list(
            (
                await db.scalars(
                    select(AuditEvent)
                    .where(
                        AuditEvent.workspace_id == context.workspace_id,
                        AuditEvent.tool_name == "web_search",
                        AuditEvent.details["run_id"].astext == str(context.run_id),
                    )
                    .order_by(AuditEvent.occurred_at)
                )
            ).all()
        )


async def _delete_committed_native_context(
    session_factory: async_sessionmaker[AsyncSession],
    context: NativeRuntimeContext,
) -> None:
    async with session_factory() as db:
        await db.execute(delete(AuditEvent).where(AuditEvent.workspace_id == context.workspace_id))
        await db.execute(
            delete(ConversationMessage).where(
                ConversationMessage.conversation_id == context.conversation_id
            )
        )
        await db.execute(
            delete(AgentRun).where(AgentRun.conversation_id == context.conversation_id)
        )
        await db.execute(delete(Conversation).where(Conversation.id == context.conversation_id))
        await db.execute(delete(Agent).where(Agent.id == context.agent_id))
        await db.execute(delete(User).where(User.id == context.user_id))
        await db.execute(delete(Workspace).where(Workspace.id == context.workspace_id))
        await db.commit()
