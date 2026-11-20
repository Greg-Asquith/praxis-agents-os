# apps/api/tests/scenarios/conftest.py

"""Runtime tools shared by deterministic Gate G5 scenarios."""

import asyncio
from importlib import import_module

import pytest
from pydantic import BaseModel
from pydantic_ai import ModelRetry, RunContext

from core.settings import settings
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_EXTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_EGRESS_EXTERNAL_WRITE,
)
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG, runtime_tool
from tests.support.embeddings import FakeEmbeddingProvider

SCENARIO_TOOL_NAMES = (
    "scenario_bad_write",
    "scenario_cancel_tool",
    "scenario_external_write",
    "scenario_fail",
)


@pytest.fixture(autouse=True)
def offline_memory_embeddings(monkeypatch: pytest.MonkeyPatch):
    """Embeds memory writes and recall queries offline, so turns never call a provider."""
    provider = FakeEmbeddingProvider()

    async def fake_embed_texts(_db, texts, **_kwargs):
        return await provider.embed_texts(
            texts, model=settings.EMBEDDINGS_MODEL, dimensions=settings.EMBEDDINGS_DIMENSIONS
        )

    monkeypatch.setattr("services.memories.utils.embed_texts", fake_embed_texts)
    # The package re-exports the function under the module's name, so patch the module itself.
    monkeypatch.setattr(
        import_module("services.memories.search_memories"), "embed_texts", fake_embed_texts
    )


class ScenarioWriteOutput(BaseModel):
    ok: bool


@pytest.fixture(autouse=True)
def scenario_runtime_tools():
    for name in SCENARIO_TOOL_NAMES:
        RUNTIME_TOOL_CATALOG.pop(name, None)

    @runtime_tool(
        name="scenario_fail",
        provider="test",
        description="Fail deterministically for a runtime scenario.",
        configurable=False,
    )
    async def scenario_fail() -> str:
        raise ModelRetry("scenario failure")

    @runtime_tool(
        name="scenario_bad_write",
        provider="test",
        description="Return an invalid write result for a runtime scenario.",
        effect=TOOL_EFFECT_WRITE,
        output_model=ScenarioWriteOutput,
        configurable=False,
    )
    async def scenario_bad_write() -> dict[str, str]:
        return {"wrong": "shape"}

    @runtime_tool(
        name="scenario_external_write",
        provider="test",
        description="Perform a deterministic external write for a runtime scenario.",
        effect=TOOL_EFFECT_WRITE,
        effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
        egress=TOOL_EGRESS_EXTERNAL_WRITE,
        output_model=ScenarioWriteOutput,
        configurable=False,
    )
    async def scenario_external_write(value: str = "ok") -> dict[str, bool]:
        return {"ok": bool(value)}

    @runtime_tool(
        name="scenario_cancel_tool",
        provider="test",
        description="Wait until cancelled for a runtime scenario.",
        takes_ctx=True,
        configurable=False,
    )
    async def scenario_cancel_tool(ctx: RunContext[RuntimeDeps]) -> str:
        del ctx
        await asyncio.Event().wait()
        return "unreachable"

    yield

    for name in SCENARIO_TOOL_NAMES:
        RUNTIME_TOOL_CATALOG.pop(name, None)
