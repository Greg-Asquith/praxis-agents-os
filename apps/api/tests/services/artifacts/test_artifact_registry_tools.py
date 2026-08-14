# apps/api/tests/services/artifacts/test_artifact_registry_tools.py

"""Artifact registry and CSP contract tests."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from pydantic import ValidationError
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import set_session_tenant_context
from core.exceptions.general import NotFoundError
from core.settings import Settings, settings
from models.artifacts import Artifact
from models.workspace import Workspace
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.entity_references.domain import ArtifactReference
from services.agents.runtime.tools.artifacts import (
    list_artifacts,
    read_artifact,
)
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    TOOL_EFFECT_SCOPE_EXTERNAL,
    TOOL_EFFECT_SCOPE_INTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_EGRESS_NONE,
    TOOL_POLICY_AUTO,
)
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from services.artifacts import create_artifact, update_artifact
from services.artifacts.create_view_url import require_valid_artifact_view_signature
from services.artifacts.domain import (
    ARTIFACT_CSP_CDN_HOSTS,
    CREATABLE_ARTIFACT_TYPES,
    artifact_frame_ancestors,
    build_html_csp,
)
from services.artifacts.schemas import (
    ArtifactListToolResult,
    ArtifactReadToolResult,
    ArtifactToolResult,
)
from tests.factories import (
    build_artifact,
    build_artifact_revision,
    build_user,
    build_workspace,
)
from tests.support.storage import reset_storage_provider_cache


@pytest.fixture
def local_storage_settings(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "APP_BASE_URL", "http://testserver")
    reset_storage_provider_cache()
    try:
        yield
    finally:
        reset_storage_provider_cache()


def _run_context(db: AsyncSession, workspace: Workspace) -> RunContext[RuntimeDeps]:
    return RunContext(
        deps=cast(RuntimeDeps, SimpleNamespace(db=db, workspace=workspace)),
        model=TestModel(),
        usage=RunUsage(),
    )


def _reference(artifact: Artifact) -> ArtifactReference:
    return ArtifactReference(
        entity_id=artifact.id,
        label=artifact.title,
        description=f"{artifact.artifact_type.title()} artifact",
    )


def test_artifact_tools_are_auto_mounted_auto_default_external_writes() -> None:
    assert [name for name in sorted(RUNTIME_TOOL_CATALOG) if "artifact" in name] == [
        "create_artifact",
        "list_artifacts",
        "read_artifact",
        "update_artifact",
    ]
    for name in ("create_artifact", "update_artifact"):
        definition = RUNTIME_TOOL_CATALOG[name]
        assert definition.effect == TOOL_EFFECT_WRITE
        assert definition.effect_scope == TOOL_EFFECT_SCOPE_EXTERNAL
        assert definition.default_policy == TOOL_POLICY_AUTO
        assert definition.supports_approval is True
        assert definition.supports_auto is True
        assert definition.output_model is ArtifactToolResult
        assert definition.configurable is False
        assert definition.auto_mount is True
        assert definition.code_eligible is False
    for name, output_model in (
        ("list_artifacts", ArtifactListToolResult),
        ("read_artifact", ArtifactReadToolResult),
    ):
        definition = RUNTIME_TOOL_CATALOG[name]
        assert definition.effect == TOOL_EFFECT_READ
        assert definition.effect_scope == TOOL_EFFECT_SCOPE_INTERNAL
        assert definition.egress == TOOL_EGRESS_NONE
        assert definition.default_policy == TOOL_POLICY_AUTO
        assert definition.supports_auto is True
        assert definition.output_model is output_model
        assert definition.configurable is False
        assert definition.auto_mount is True
        assert definition.code_eligible is False
    assert "image-ref" not in CREATABLE_ARTIFACT_TYPES


async def test_list_artifacts_returns_bounded_workspace_summaries_newest_first(
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    actor = build_user(email=f"artifact-list-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"artifact-list-{uuid4().hex[:8]}")
    other_workspace = build_workspace(slug=f"artifact-other-{uuid4().hex[:8]}")
    db_session.add_all([actor, workspace, other_workspace])
    await db_session.flush()
    await set_session_tenant_context(
        db_session,
        workspace_id=other_workspace.id,
        user_id=actor.id,
    )
    await create_artifact(
        db_session,
        workspace=other_workspace,
        title="Quarterly private",
        artifact_type="markdown",
        content="Other workspace",
        actor_user_id=actor.id,
    )
    await set_session_tenant_context(
        db_session,
        workspace_id=workspace.id,
        user_id=actor.id,
    )
    older, _ = await create_artifact(
        db_session,
        workspace=workspace,
        title="Quarterly notes",
        artifact_type="markdown",
        content="Old notes",
        actor_user_id=actor.id,
    )
    newer, _ = await create_artifact(
        db_session,
        workspace=workspace,
        title="Quarterly report",
        artifact_type="markdown",
        content="First draft",
        actor_user_id=actor.id,
    )
    await update_artifact(
        db_session,
        workspace=workspace,
        artifact_id=newer.id,
        content="Second draft",
        actor_user_id=actor.id,
    )
    deleted, _ = await create_artifact(
        db_session,
        workspace=workspace,
        title="Quarterly deleted",
        artifact_type="markdown",
        content="Deleted",
        actor_user_id=actor.id,
    )
    deleted.soft_delete(deleted_by=actor.id, cascade=False)
    older.updated_at = datetime.now(UTC) - timedelta(days=1)
    newer.updated_at = datetime.now(UTC)
    await db_session.flush()

    result = ArtifactListToolResult.model_validate(
        await list_artifacts(_run_context(db_session, workspace), search="Quarterly", limit=1)
    )

    assert result.total == 2
    assert result.returned == 1
    assert [item.id for item in result.items] == [str(newer.id)]
    [summary] = result.items
    assert summary.reference.entity_id == newer.id
    assert summary.title == "Quarterly report"
    assert summary.version_count == 2
    assert summary.conversation_id is None
    search_result = ArtifactListToolResult.model_validate(
        await list_artifacts(_run_context(db_session, workspace), search="notes", limit=50)
    )
    assert [item.id for item in search_result.items] == [str(older.id)]
    assert search_result.total == 1
    input_schema = RUNTIME_TOOL_CATALOG["list_artifacts"].serialized_input_schema()
    assert input_schema is not None
    assert input_schema["properties"]["limit"]["maximum"] == 50


async def test_list_artifacts_empty_workspace_is_well_formed(
    db_session: AsyncSession,
) -> None:
    workspace = build_workspace(slug=f"artifact-empty-{uuid4().hex[:8]}")
    db_session.add(workspace)
    await db_session.flush()

    result = await list_artifacts(_run_context(db_session, workspace))

    assert result == {"items": [], "total": 0, "returned": 0}


async def test_read_artifact_returns_current_content_and_truncation_metadata(
    db_session: AsyncSession,
    local_storage_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor = build_user(email=f"artifact-read-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"artifact-read-{uuid4().hex[:8]}")
    db_session.add_all([actor, workspace])
    await db_session.flush()
    artifact, _ = await create_artifact(
        db_session,
        workspace=workspace,
        title="Shared report",
        artifact_type="markdown",
        content="First draft",
        actor_user_id=actor.id,
    )
    await update_artifact(
        db_session,
        workspace=workspace,
        artifact_id=artifact.id,
        content="Second draft with details",
        actor_user_id=actor.id,
    )

    full_result = ArtifactReadToolResult.model_validate(
        await read_artifact(_run_context(db_session, workspace), _reference(artifact))
    )
    assert full_result.content == "Second draft with details"
    assert full_result.truncated is False
    monkeypatch.setattr(settings, "ARTIFACT_READ_TOOL_MAX_CHARS", 12)

    result = ArtifactReadToolResult.model_validate(
        await read_artifact(_run_context(db_session, workspace), _reference(artifact))
    )

    assert result.id == str(artifact.id)
    assert result.reference.entity_id == artifact.id
    assert result.revision_number == 2
    assert result.content == "Second draft"
    assert result.truncated is True
    assert result.size_bytes == len(b"Second draft with details")
    assert result.content_type == "text/markdown"


async def test_read_image_artifact_never_returns_signed_url(
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    workspace = build_workspace(slug=f"artifact-image-{uuid4().hex[:8]}")
    db_session.add(workspace)
    await db_session.flush()
    revision_id = uuid4()
    artifact = build_artifact(
        workspace=workspace,
        artifact_type="image-ref",
        title="Generated chart",
    )
    db_session.add(artifact)
    await db_session.flush()
    revision = build_artifact_revision(
        artifact=artifact,
        revision_id=revision_id,
        content_type="image/png",
        size_bytes=321,
    )
    db_session.add(revision)
    await db_session.flush()
    artifact.current_version_id = revision.id
    await db_session.flush()

    result = await read_artifact(_run_context(db_session, workspace), _reference(artifact))
    serialized = json.dumps(result)

    assert result["content"] is None
    assert result["truncated"] is False
    assert result["size_bytes"] == 321
    assert result["note"] == "Binary artifacts are viewable only in the Artifacts UI."
    assert "download_url" not in serialized
    assert "sig=" not in serialized
    assert "object_key" not in serialized


async def test_read_artifact_retries_for_unknown_deleted_and_cross_workspace_ids(
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    actor = build_user(email=f"artifact-missing-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"artifact-missing-{uuid4().hex[:8]}")
    other_workspace = build_workspace(slug=f"artifact-scope-{uuid4().hex[:8]}")
    db_session.add_all([actor, workspace, other_workspace])
    await db_session.flush()
    await set_session_tenant_context(
        db_session,
        workspace_id=other_workspace.id,
        user_id=actor.id,
    )
    scoped, _ = await create_artifact(
        db_session,
        workspace=other_workspace,
        title="Private report",
        artifact_type="markdown",
        content="Private",
        actor_user_id=actor.id,
    )
    await set_session_tenant_context(
        db_session,
        workspace_id=workspace.id,
        user_id=actor.id,
    )
    deleted, _ = await create_artifact(
        db_session,
        workspace=workspace,
        title="Deleted report",
        artifact_type="markdown",
        content="Gone",
        actor_user_id=actor.id,
    )
    deleted.soft_delete(deleted_by=actor.id, cascade=False)
    await db_session.flush()

    references = [
        _reference(deleted),
        _reference(scoped),
        ArtifactReference(entity_id=uuid4(), label="Unknown artifact"),
    ]
    for reference in references:
        with pytest.raises(ModelRetry, match="Unknown artifact id"):
            await read_artifact(_run_context(db_session, workspace), reference)


def test_html_csp_has_no_external_content_hosts() -> None:
    csp = build_html_csp(
        connect_src="'none'",
        frame_ancestors=artifact_frame_ancestors(),
    )
    assert ARTIFACT_CSP_CDN_HOSTS == ()
    assert "cdn.jsdelivr.net" not in csp
    assert "unpkg.com" not in csp
    directives = {
        parts[0]: parts[1:] for directive in csp.split(";") if (parts := directive.strip().split())
    }
    for name in ("script-src", "style-src", "font-src", "img-src", "connect-src"):
        for source in directives[name]:
            parsed = urlsplit(source)
            assert not (parsed.scheme and parsed.netloc)
    assert directives["connect-src"] == ["'none'"]
    assert directives["sandbox"] == ["allow-scripts"]


def test_expired_view_capability_fails_before_lookup() -> None:
    with pytest.raises(NotFoundError):
        require_valid_artifact_view_signature(
            workspace_id=uuid4(),
            artifact_id=uuid4(),
            version_id=uuid4(),
            expires=0,
            signature="v1." + ("0" * 64),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ARTIFACT_VIEW_URL_TTL_SECONDS", 0),
        ("ARTIFACT_VIEW_URL_TTL_SECONDS", 3601),
        ("ARTIFACT_MAX_CONTENT_BYTES", 0),
        ("ARTIFACT_MAX_CONTENT_BYTES", 10_485_761),
        ("ARTIFACT_READ_TOOL_MAX_CHARS", 999),
    ],
)
def test_artifact_limits_reject_unsafe_values(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: value})
