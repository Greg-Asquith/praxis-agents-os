# apps/api/tests/services/kb/test_write_policy.py

"""Knowledge-base write-policy invariants."""

from uuid import uuid4

import pytest

from core.exceptions.general import AppValidationError, ConflictError, NotFoundError
from models.kb import KBDocument
from services.kb.write_policy import KBProvenance, enforce_kb_write_policy


def _document(
    *,
    workspace_id=None,
    is_private: bool = False,
    created_by_user_id=None,
) -> KBDocument:
    return KBDocument(
        id=uuid4(),
        workspace_id=workspace_id or uuid4(),
        title="Existing",
        source_type="manual",
        content_hash="a" * 64,
        is_private=is_private,
        annotation_enabled=False,
        created_by_user_id=created_by_user_id,
    )


def _user_provenance(**overrides) -> KBProvenance:
    values = {"actor_kind": "user", "user_id": uuid4(), "source_type": "manual"}
    values.update(overrides)
    return KBProvenance(**values)


@pytest.mark.parametrize(
    "provenance",
    [
        KBProvenance(actor_kind="user"),
        KBProvenance(actor_kind="agent", agent_id=uuid4()),
        KBProvenance(actor_kind="agent", run_id=uuid4()),
        KBProvenance(actor_kind="user", user_id=uuid4(), source_type="url"),
        KBProvenance(actor_kind="system", source_type="upload"),
    ],
)
def test_required_provenance_is_enforced(provenance: KBProvenance) -> None:
    with pytest.raises(AppValidationError, match="require provenance"):
        enforce_kb_write_policy(
            workspace_id=uuid4(),
            provenance=provenance,
            title="Handbook",
            content_md="Safe content",
            is_private=False,
        )


def test_cross_workspace_update_is_not_found() -> None:
    document = _document()
    with pytest.raises(NotFoundError):
        enforce_kb_write_policy(
            workspace_id=uuid4(),
            provenance=_user_provenance(),
            title=document.title,
            content_md="Safe content",
            is_private=document.is_private,
            existing=document,
        )


def test_private_documents_can_only_move_toward_private_scope() -> None:
    workspace_id = uuid4()
    private = _document(workspace_id=workspace_id, is_private=True)
    with pytest.raises(AppValidationError, match="cannot be made workspace-shared"):
        enforce_kb_write_policy(
            workspace_id=workspace_id,
            provenance=_user_provenance(),
            title=private.title,
            content_md="Safe content",
            is_private=False,
            existing=private,
        )

    creator_id = uuid4()
    shared = _document(
        workspace_id=workspace_id,
        is_private=False,
        created_by_user_id=creator_id,
    )
    enforce_kb_write_policy(
        workspace_id=workspace_id,
        provenance=_user_provenance(user_id=creator_id),
        title=shared.title,
        content_md="Safe content",
        is_private=True,
        existing=shared,
    )
    with pytest.raises(AppValidationError, match="Only the document creator"):
        enforce_kb_write_policy(
            workspace_id=workspace_id,
            provenance=_user_provenance(),
            title=shared.title,
            content_md="Safe content",
            is_private=True,
            existing=shared,
        )


@pytest.mark.parametrize(
    "secret",
    [
        "AKIA1234567890ABCDEF",
        "ghp_" + ("a" * 36),
        "xoxb-1234567890-secret",
        "-----BEGIN PRIVATE KEY-----",
        "AIza" + ("a" * 35),
        "eyJabc.eyJdef.signature",
    ],
)
def test_detected_secret_is_rejected_without_echo(secret: str) -> None:
    with pytest.raises(AppValidationError) as caught:
        enforce_kb_write_policy(
            workspace_id=uuid4(),
            provenance=_user_provenance(),
            title="Handbook",
            content_md=f"Do not store {secret}",
            is_private=False,
        )
    assert secret not in str(caught.value)


@pytest.mark.parametrize(
    ("title", "content"),
    [
        (" ", "content"),
        ("x" * 501, "content"),
        ("Handbook", " "),
    ],
)
def test_noise_gate_rejects_invalid_content(title: str, content: str) -> None:
    with pytest.raises(AppValidationError):
        enforce_kb_write_policy(
            workspace_id=uuid4(),
            provenance=_user_provenance(),
            title=title,
            content_md=content,
            is_private=False,
        )


def test_duplicate_in_same_privacy_scope_is_a_conflict() -> None:
    duplicate = _document()
    with pytest.raises(ConflictError) as caught:
        enforce_kb_write_policy(
            workspace_id=duplicate.workspace_id,
            provenance=_user_provenance(),
            title="Duplicate",
            content_md="Safe content",
            is_private=duplicate.is_private,
            duplicate=duplicate,
        )
    assert caught.value.details["document_id"] == str(duplicate.id)


def test_compliant_write_passes() -> None:
    enforce_kb_write_policy(
        workspace_id=uuid4(),
        provenance=_user_provenance(),
        title="Operations handbook",
        content_md="Safe and useful workspace knowledge.",
        is_private=False,
    )
