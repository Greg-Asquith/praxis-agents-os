# apps/api/tests/services/platform_content/test_two_workspace_example.py

"""Exercises shared reference material and independent client deliverables."""

from uuid import uuid4

import pytest

from core.database import maintenance_async_db_session, set_session_tenant_context
from core.exceptions.general import NotFoundError
from services.artifacts.create_artifact import create_artifact
from services.artifacts.get_artifact import get_artifact
from services.artifacts.get_version_content import get_version_content
from services.artifacts.list_artifacts import list_artifacts
from services.files.copy_file import copy_file
from services.files.domain import FileCopyRequest
from services.files.get_file import get_file
from services.files.get_file_revision_content import get_file_revision_content
from services.files.list_files import list_files
from services.kb.embed_platform_chunks import embed_platform_chunks
from services.kb.get_document import get_kb_document
from services.kb.ingest_platform_document import ingest_platform_document
from services.kb.platform.create_manual_document import create_manual_document
from services.kb.schemas import PlatformKBManualDocumentCreateRequest
from services.kb.search_chunks import search_chunks
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.services.artifacts.test_platform_artifact_management import _create as publish_report
from tests.services.files.test_platform_file_management import (
    _draft as upload_template,
    _publish as publish_template,
    management_context as management_context,
)
from tests.services.kb.test_platform_knowledge_management import ingestion_job, publish
from tests.support.embeddings import FakeEmbeddingProvider
from tests.support.requests import build_test_request


async def test_platform_policy_template_and_report_in_two_workspaces(
    db_session, db_session_factory, management_context
):
    actor = management_context["actor"]
    policy_text = "Delivery policy: agree the scope and delivery date before starting work."
    template_text = "# Proposal for {client}\n\n## Delivery terms\n{policy}\n"
    policy = await create_manual_document(
        db_session,
        actor=actor,
        request=build_test_request(),
        payload=PlatformKBManualDocumentCreateRequest(
            title="Delivery policy", content_md=policy_text
        ),
    )
    job = await ingestion_job(policy.id, policy.meta["ingestion_version"])
    await ingest_platform_document(job)
    provider = FakeEmbeddingProvider()
    await embed_platform_chunks(job, provider=provider)
    policy = await publish(db_session, actor, policy)
    template = await upload_template(db_session, management_context, content=template_text.encode())
    template = await publish_template(db_session, actor, template)
    report = await publish_report(
        db_session, {"actor": actor, "workspace": management_context["workspace"]}
    )
    assert policy.is_published and template.is_published and report.is_published
    assert policy.workspace_id is template.workspace_id is report.workspace_id is None

    clients = []
    async with maintenance_async_db_session() as db:
        for name in ("Client A", "Client B"):
            user = build_user(email=f"client-{uuid4().hex}@example.com")
            workspace = build_workspace(name=name, slug=f"client-{uuid4().hex}")
            membership = build_workspace_membership(workspace_id=workspace.id, user_id=user.id)
            db.add_all([user, workspace, membership])
            clients.append({"actor": user, "workspace": workspace, "membership": membership})
    assert clients[0]["workspace"].id != clients[1]["workspace"].id

    deliverables = []
    for client in clients:
        workspace, user = client["workspace"], client["actor"]
        async with db_session_factory() as tenant:
            await set_session_tenant_context(tenant, workspace_id=workspace.id, user_id=user.id)
            hits = await search_chunks(
                tenant,
                workspace_id=workspace.id,
                user_id=user.id,
                query="delivery policy",
                provider=provider,
            )
            assert hits.mode == "hybrid"
            assert [(hit.document_id, hit.scope) for hit in hits.results] == [
                (policy.id, "platform")
            ]
            readable_policy = await get_kb_document(
                tenant, workspace_id=workspace.id, user_id=user.id, document_id=policy.id
            )
            assert readable_policy.content_md == policy_text
            files = await list_files(tenant, workspace=workspace)
            assert [(file.id, file.scope) for file in files.files] == [(template.id, "platform")]
            template_content = await get_file_revision_content(
                tenant,
                workspace=workspace,
                actor=user,
                request=build_test_request(),
                file_id=template.id,
                revision_id=template.current_revision_id,
            )
            assert template_content.content == template_text
            reports = await list_artifacts(tenant, workspace_id=workspace.id, limit=20, offset=0)
            assert [(item.id, item.scope) for item in reports.items] == [(report.id, "platform")]
            example = await get_artifact(tenant, workspace_id=workspace.id, artifact_id=report.id)
            example_content = await get_version_content(
                tenant, artifact=example, version_id=example.current_version_id
            )
            assert example_content.content == "<p>Selected report</p>"
            local_template = await copy_file(
                tenant,
                **client,
                request=build_test_request(),
                file_id=template.id,
                payload=FileCopyRequest(
                    revision_id=template.current_revision_id, request_id=uuid4()
                ),
            )
            output_text = template_content.content.format(
                client=workspace.name, policy=readable_policy.content_md
            )
            output, version = await create_artifact(
                tenant,
                workspace=workspace,
                title=f"{workspace.name} proposal",
                artifact_type="markdown",
                content=output_text,
                actor_user_id=user.id,
            )
            await tenant.commit()
            assert local_template.scope == output.scope == "workspace"
            assert local_template.workspace_id == output.workspace_id == workspace.id
            assert local_template.id != template.id
            assert version.object_key.startswith(f"workspaces/{workspace.id}/")
            deliverables.append((local_template, output.id, version.id, output_text))

    for index, client in enumerate(clients):
        workspace, user = client["workspace"], client["actor"]
        own_template, own_output_id, version_id, output_text = deliverables[index]
        other_template, other_output_id, _, _ = deliverables[1 - index]
        async with db_session_factory() as tenant:
            await set_session_tenant_context(tenant, workspace_id=workspace.id, user_id=user.id)
            files = await list_files(tenant, workspace=workspace)
            assert {file.id for file in files.files} == {template.id, own_template.id}
            reports = await list_artifacts(tenant, workspace_id=workspace.id, limit=20, offset=0)
            assert {item.id for item in reports.items} == {report.id, own_output_id}
            own_output = await get_artifact(
                tenant, workspace_id=workspace.id, artifact_id=own_output_id
            )
            content = await get_version_content(tenant, artifact=own_output, version_id=version_id)
            assert content.content == output_text
            with pytest.raises(NotFoundError):
                await get_file(tenant, workspace=workspace, file_id=other_template.id)
            with pytest.raises(NotFoundError):
                await get_artifact(tenant, workspace_id=workspace.id, artifact_id=other_output_id)
            unchanged = await get_file_revision_content(
                tenant,
                workspace=workspace,
                actor=user,
                request=build_test_request(),
                file_id=template.id,
                revision_id=template.current_revision_id,
            )
            assert unchanged.content == template_text
