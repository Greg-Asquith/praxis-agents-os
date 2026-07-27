"""Deterministic duplicate-threshold calibration fixtures."""

from core.settings import settings
from evals.memory_calibration import calibrate_memory_dedup
from tests.support.embeddings import FakeEmbeddingProvider


async def test_fake_provider_calibrates_duplicate_and_contradiction_behavior() -> None:
    scores = await calibrate_memory_dedup(FakeEmbeddingProvider())
    assert scores["duplicate"] >= settings.MEMORY_DEDUP_SIMILARITY
    assert scores["contradiction"] >= settings.MEMORY_DEDUP_SIMILARITY
    assert scores["contradiction"] > scores["distinct"]
