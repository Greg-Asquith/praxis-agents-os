# apps/api/tests/services/embeddings/test_settings.py

"""Embedding settings validation tests."""

import pytest
from pydantic import ValidationError

from core.settings import Settings
from tests.support.settings import production_settings


def test_embedding_settings_defaults() -> None:
    resolved = Settings()

    assert resolved.EMBEDDINGS_PROVIDER == "openai"
    assert resolved.EMBEDDINGS_MODEL == "text-embedding-3-small"
    assert resolved.EMBEDDINGS_DIMENSIONS == 1024


@pytest.mark.parametrize("dimensions", [511, 1025])
def test_embedding_dimensions_are_bounded(dimensions: int) -> None:
    with pytest.raises(ValidationError):
        Settings(EMBEDDINGS_DIMENSIONS=dimensions)


def test_ollama_requires_explicit_base_url() -> None:
    with pytest.raises(ValidationError, match="EMBEDDINGS_OLLAMA_BASE_URL"):
        Settings(EMBEDDINGS_PROVIDER="ollama", EMBEDDINGS_OLLAMA_BASE_URL=None)


def test_production_openai_embeddings_require_api_key() -> None:
    with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
        production_settings(OPENAI_API_KEY=None)


@pytest.mark.parametrize("api_key", [None, " "])
def test_production_google_embeddings_require_api_key(api_key: str | None) -> None:
    with pytest.raises(ValidationError, match="GOOGLE_API_KEY"):
        production_settings(
            EMBEDDINGS_PROVIDER="google",
            EMBEDDINGS_MODEL="gemini-embedding-2",
            GOOGLE_API_KEY=api_key,
        )


@pytest.mark.parametrize(
    ("vertex_project", "gcp_project_id"),
    [
        ("vertex-project", None),
        (None, "deployment-project"),
    ],
)
def test_production_google_embeddings_accept_vertex_project_fallback(
    vertex_project: str | None,
    gcp_project_id: str | None,
) -> None:
    resolved = production_settings(
        EMBEDDINGS_PROVIDER="google",
        EMBEDDINGS_MODEL="gemini-embedding-2",
        GOOGLE_API_KEY=None,
        GOOGLE_VERTEX_AI=True,
        GOOGLE_VERTEX_PROJECT=vertex_project,
        GCP_PROJECT_ID=gcp_project_id,
    )

    assert resolved.GOOGLE_VERTEX_AI is True


@pytest.mark.parametrize(
    ("vertex_project", "gcp_project_id"),
    [
        (None, None),
        (" ", " "),
    ],
)
def test_production_google_embeddings_require_vertex_project(
    vertex_project: str | None,
    gcp_project_id: str | None,
) -> None:
    with pytest.raises(
        ValidationError,
        match="GOOGLE_VERTEX_PROJECT or GCP_PROJECT_ID",
    ):
        production_settings(
            EMBEDDINGS_PROVIDER="google",
            EMBEDDINGS_MODEL="gemini-embedding-2",
            GOOGLE_API_KEY=None,
            GOOGLE_VERTEX_AI=True,
            GOOGLE_VERTEX_PROJECT=vertex_project,
            GCP_PROJECT_ID=gcp_project_id,
        )
