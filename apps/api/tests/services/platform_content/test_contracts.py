"""Ownership input rejection and server-derived platform management authority."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from core.settings import settings
from services.artifacts.schemas import ArtifactUpdateRequest
from services.artifacts.utils import artifact_to_read, artifact_to_summary
from services.files.domain import (
    FileConfirmRequest,
    FileEditRequest,
    FileMoveRequest,
    FileRestoreRequest,
    FileUpdateRequest,
    FileUploadRequest,
)
from services.files.utils import file_to_read
from services.kb.schemas import KBDocumentListItem, KBDocumentRead, KBDocumentUpdateRequest
from services.skills.schemas import SkillRead, SkillUpdateRequest
from tests.factories import (
    build_artifact,
    build_file,
    build_kb_document,
    build_skill,
    build_user,
    build_workspace,
)


@pytest.mark.parametrize(
    "schema,payload",
    [
        (SkillUpdateRequest, {"description": "Updated guidance"}),
        (FileUpdateRequest, {"name": "Renamed"}),
        (
            FileUploadRequest,
            {
                "filename": "a.txt",
                "content_type": "text/plain",
                "size_bytes": 1,
                "file_id": str(uuid4()),
            },
        ),
        (FileConfirmRequest, {"upload_token": "signed-upload"}),
        (FileEditRequest, {"content": "text", "expected_current_revision_id": str(uuid4())}),
        (
            FileRestoreRequest,
            {"revision_id": str(uuid4()), "expected_current_revision_id": str(uuid4())},
        ),
        (FileMoveRequest, {"file_ids": [str(uuid4())]}),
        (ArtifactUpdateRequest, {"content": "text"}),
        (KBDocumentUpdateRequest, {"title": "Renamed"}),
    ],
)
@pytest.mark.parametrize(
    "field,value",
    [
        ("scope", "platform"),
        ("workspace_id", str(uuid4())),
        ("is_published", True),
        ("published_revision_id", str(uuid4())),
        ("published_version_id", str(uuid4())),
        ("can_manage_platform", True),
    ],
)
def test_ordinary_updates_reject_ownership_and_publication(schema, payload, field, value):
    with pytest.raises(ValidationError) as error:
        schema.model_validate({**payload, field: value})
    assert any(
        item["loc"] == (field,) and item["type"] == "extra_forbidden"
        for item in error.value.errors()
    )


@pytest.mark.parametrize("scope", ["workspace", "platform"])
@pytest.mark.parametrize("actor_kind", ["admin", "member", "absent"])
@pytest.mark.parametrize("deleted", [False, True])
def test_parent_projections_expose_ownership_and_platform_authority(
    monkeypatch, scope, actor_kind, deleted
):
    monkeypatch.setattr(settings, "SUPER_ADMIN_EMAILS", "admin@example.com")
    actor = None if actor_kind == "absent" else build_user(email=f"{actor_kind}@example.com")
    workspace = build_workspace()
    fields = {
        "scope": scope,
        "workspace_id": None if scope == "platform" else workspace.id,
        "is_published": scope == "platform",
        "deleted": deleted,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    file = build_file(workspace=workspace, current_revision_id=uuid4(), **fields)
    artifact = build_artifact(workspace=workspace, current_version_id=uuid4(), **fields)
    document = build_kb_document(
        workspace=workspace, is_private=False, processing_attempts=0, **fields
    )
    skill_fields = {key: value for key, value in fields.items() if key != "is_published"}
    skill = build_skill(
        workspace=workspace,
        created_by=actor or build_user(),
        id=uuid4(),
        documentation_refs={},
        is_active=True,
        is_favorite=False,
        **skill_fields,
    )
    skill_response = SkillRead.from_skill(skill, actor=actor)
    assert skill_response.scope == scope
    assert skill_response.workspace_id == fields["workspace_id"]
    assert skill_response.can_manage_platform == (
        scope == "platform" and actor_kind == "admin" and not deleted
    )
    projections = [
        file_to_read(file, folder_name=None, actor=actor),
        artifact_to_read(artifact, [], actor=actor),
        artifact_to_summary(artifact, version_count=1, actor=actor),
        KBDocumentRead.from_document(document, actor=actor),
        KBDocumentListItem.from_document(document, actor=actor),
    ]
    for response in projections:
        data = response.model_dump(mode="json")
        assert data["scope"] == scope
        assert data["workspace_id"] == (None if scope == "platform" else str(workspace.id))
        assert data["is_published"] == (scope == "platform")
        assert data["can_manage_platform"] == (
            scope == "platform" and actor_kind == "admin" and not deleted
        )


@pytest.mark.parametrize("role", ["owner", "admin", "member", "read_only"])
@pytest.mark.parametrize(
    "state",
    [
        "published",
        "draft",
        "withdrawn",
        "deleted",
        "removed_member",
        "wrong_actor",
        "local",
        "other_workspace",
    ],
)
def test_artifact_edit_capability_uses_membership_and_parent_visibility(monkeypatch, role, state):
    from models.workspace import WorkspaceRole
    from tests.factories import build_workspace_membership

    monkeypatch.setattr(settings, "SUPER_ADMIN_EMAILS", "")
    actor = build_user()
    workspace = build_workspace()
    membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=actor.id,
        role=WorkspaceRole(role),
    )
    membership.deleted = state == "removed_member"
    if state == "wrong_actor":
        membership.user_id = uuid4()
    artifact = build_artifact(
        workspace=workspace,
        scope="workspace" if state in {"local", "other_workspace"} else "platform",
        workspace_id=(workspace.id if state == "local" else uuid4())
        if state in {"local", "other_workspace"}
        else None,
        current_version_id=uuid4(),
        is_published=state not in {"draft", "withdrawn", "local", "other_workspace"},
        deleted=state == "deleted",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    expected = role != "read_only" and state in {"published", "local"}
    for response in [
        artifact_to_read(artifact, [], actor=actor, membership=membership),
        artifact_to_summary(artifact, version_count=1, actor=actor, membership=membership),
    ]:
        assert response.can_edit is expected
        assert response.can_manage_platform is False
