# apps/api/tests/services/embeddings/test_embed_texts.py

"""Public embedding operation tests."""

import importlib
from collections.abc import Sequence
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from services.ai_usage.domain import PURPOSE_EMBEDDING_KB_SEARCH, AIUsageEventData
from services.embeddings.domain import (
    EmbeddingBatch,
    EmbeddingConfigurationError,
    EmbeddingProvider,
    EmbeddingProviderError,
)
from services.embeddings.embed_texts import embed_texts
from services.embeddings.get_embedding_usage import get_embedding_usage
from tests.factories import build_workspace

pytestmark = pytest.mark.asyncio
embed_texts_module = importlib.import_module("services.embeddings.embed_texts")


class RecordingProvider(EmbeddingProvider):
    provider = "recording"

    def __init__(self, *, omit_last: bool = False) -> None:
        self.call_sizes: list[int] = []
        self.omit_last = omit_last

    async def embed_texts(
        self,
        texts: Sequence[str],
        *,
        model: str,
        dimensions: int,
    ) -> EmbeddingBatch:
        self.call_sizes.append(len(texts))
        vectors = [[float(index)] * dimensions for index in range(len(texts))]
        if self.omit_last:
            vectors = vectors[:-1]
        return EmbeddingBatch(
            vectors=vectors,
            total_tokens=len(texts) * 3,
            provider=self.provider,
            model=model,
            dimensions=dimensions,
        )


class FailingSecondProvider(RecordingProvider):
    async def embed_texts(self, texts, *, model, dimensions):
        if self.call_sizes:
            self.call_sizes.append(len(texts))
            raise EmbeddingProviderError("later batch failed")
        return await super().embed_texts(texts, model=model, dimensions=dimensions)


async def _workspace(db: AsyncSession):
    workspace = build_workspace(slug=f"embeddings-{uuid4().hex}")
    db.add(workspace)
    await db.flush()
    return workspace


async def test_batches_preserve_order_and_meter_provider_tokens(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = await _workspace(db_session)
    provider = RecordingProvider()
    recorded: list[AIUsageEventData] = []

    async def record(event: AIUsageEventData) -> bool:
        recorded.append(event)
        return True

    monkeypatch.setattr(embed_texts_module, "record_ai_usage_durable", record)
    monkeypatch.setattr(settings, "EMBEDDINGS_MAX_BATCH_TEXTS", 2)

    result = await embed_texts(
        db_session,
        ["one", "two", "three", "four", "five"],
        workspace_id=workspace.id,
        purpose=PURPOSE_EMBEDDING_KB_SEARCH,
        provider=provider,
    )

    assert provider.call_sizes == [2, 2, 1]
    assert len(result.vectors) == 5
    assert result.total_tokens == 15
    assert len(recorded) == 1
    assert recorded[0].requests == 3
    assert recorded[0].input_tokens == 15
    assert await get_embedding_usage(db_session, workspace_id=workspace.id) == 15


async def test_empty_input_short_circuits_without_provider_or_metering(
    db_session: AsyncSession,
) -> None:
    workspace = await _workspace(db_session)
    provider = RecordingProvider()

    result = await embed_texts(
        db_session,
        [],
        workspace_id=workspace.id,
        purpose=PURPOSE_EMBEDDING_KB_SEARCH,
        provider=provider,
    )

    assert result.vectors == []
    assert provider.call_sizes == []
    assert await get_embedding_usage(db_session, workspace_id=workspace.id) == 0


async def test_invalid_text_names_its_index(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = await _workspace(db_session)
    monkeypatch.setattr(settings, "EMBEDDINGS_MAX_TEXT_CHARS", 4)

    with pytest.raises(EmbeddingConfigurationError, match="index 1"):
        await embed_texts(
            db_session,
            ["okay", "too long"],
            workspace_id=workspace.id,
            purpose=PURPOSE_EMBEDDING_KB_SEARCH,
            provider=RecordingProvider(),
        )


async def test_soft_budget_warns_only_on_the_crossing_call(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    usage_module = importlib.import_module("services.embeddings.record_embedding_usage")
    workspace = await _workspace(db_session)
    monkeypatch.setattr(settings, "EMBEDDINGS_MONTHLY_TOKEN_BUDGET", 5)
    warnings: list[str] = []

    def record_warning(message: str, *args: object, **kwargs: object) -> None:
        warnings.append(message)

    monkeypatch.setattr(usage_module.logger, "warning", record_warning)
    await embed_texts(
        db_session,
        ["first", "second"],
        workspace_id=workspace.id,
        purpose=PURPOSE_EMBEDDING_KB_SEARCH,
        provider=RecordingProvider(),
    )
    await embed_texts(
        db_session,
        ["third"],
        workspace_id=workspace.id,
        purpose=PURPOSE_EMBEDDING_KB_SEARCH,
        provider=RecordingProvider(),
    )

    assert len(warnings) == 1
    assert "crossed its soft monthly budget" in warnings[0]
    assert await get_embedding_usage(db_session, workspace_id=workspace.id) == 9


async def test_provider_length_mismatch_fails_before_metering(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = await _workspace(db_session)
    recorded: list[AIUsageEventData] = []

    async def record(event: AIUsageEventData) -> bool:
        recorded.append(event)
        return True

    monkeypatch.setattr(embed_texts_module, "record_ai_usage_durable", record)

    with pytest.raises(EmbeddingProviderError, match="unexpected number"):
        await embed_texts(
            db_session,
            ["first", "second"],
            workspace_id=workspace.id,
            purpose=PURPOSE_EMBEDDING_KB_SEARCH,
            provider=RecordingProvider(omit_last=True),
        )

    assert await get_embedding_usage(db_session, workspace_id=workspace.id) == 0
    assert recorded[0].requests == 1
    assert recorded[0].input_tokens == 6


async def test_invalid_purpose_fails_before_provider_call(db_session: AsyncSession) -> None:
    workspace = await _workspace(db_session)
    provider = RecordingProvider()

    with pytest.raises(ValueError, match="Unknown AI usage purpose"):
        await embed_texts(
            db_session,
            ["text"],
            workspace_id=workspace.id,
            purpose="invalid",  # type: ignore[arg-type] - runtime boundary probe
            provider=provider,
        )
    assert provider.call_sizes == []


async def test_later_batch_failure_records_completed_batches_only(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = await _workspace(db_session)
    provider = FailingSecondProvider()
    recorded: list[AIUsageEventData] = []
    monkeypatch.setattr(settings, "EMBEDDINGS_MAX_BATCH_TEXTS", 1)

    async def record(event: AIUsageEventData) -> bool:
        recorded.append(event)
        return True

    monkeypatch.setattr(embed_texts_module, "record_ai_usage_durable", record)
    with pytest.raises(EmbeddingProviderError, match="later batch failed"):
        await embed_texts(
            db_session,
            ["first", "second"],
            workspace_id=workspace.id,
            purpose=PURPOSE_EMBEDDING_KB_SEARCH,
            provider=provider,
        )

    assert recorded[0].requests == 1
    assert recorded[0].input_tokens == 3
    assert await get_embedding_usage(db_session, workspace_id=workspace.id) == 0
