"""Discovery job enqueue and terminal notification behavior."""

from dataclasses import replace
from importlib import import_module

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationCredentialUnavailableError,
)
from models.integrations import (
    ExternalCredential,
    IntegrationConnection,
    IntegrationDiscoveryRun,
    IntegrationResource,
)
from models.jobs import Job
from models.notification import Notification
from models.user import User
from models.workspace import Workspace
from services.integrations.discovery.enqueue_discovery import enqueue_discovery
from services.integrations.discovery.handlers import discover_resources
from services.integrations.discovery.recover_orphaned import recover_orphaned_discoveries
from services.jobs.registry import JOB_HANDLERS
from tests.factories import (
    build_external_credential,
    build_integration_connection,
    build_user,
    build_workspace,
)


async def test_enqueue_discovery_deduplicates_in_flight_work(
    db_session: AsyncSession,
    discovery_connection: dict[str, object],
) -> None:
    connection = discovery_connection["connection"]
    first = await enqueue_discovery(db_session, connection=connection)
    second = await enqueue_discovery(db_session, connection=connection)
    assert first.id == second.id
    assert first.initiated_by_user_id is None


async def test_user_owned_discovery_uses_user_concurrency_bucket(
    db_session: AsyncSession,
) -> None:
    user = build_user()
    credential = build_external_credential()
    db_session.add_all([user, credential])
    await db_session.flush()
    connection = build_integration_connection(
        credential=credential,
        user=user,
        owner_user_id=user.id,
        status="discovery_pending",
    )
    db_session.add(connection)
    await db_session.flush()

    job = await enqueue_discovery(db_session, connection=connection)

    assert job.workspace_id is None
    assert job.concurrency_user_id == user.id
    assert job.initiated_by_user_id is None


async def test_recover_orphaned_discovery_recreates_missing_work(
    db_session: AsyncSession,
    discovery_connection: dict[str, object],
) -> None:
    connection = discovery_connection["connection"]

    assert await recover_orphaned_discoveries(db_session) == 1
    assert await recover_orphaned_discoveries(db_session) == 0

    job = await db_session.scalar(
        select(Job).where(
            Job.kind == "integrations.discover_resources",
            Job.subject_id == connection.id,
        )
    )
    assert job is not None
    assert job.status == "pending"


async def test_terminal_handler_failure_cannot_leave_pending_status(
    db_session: AsyncSession,
    discovery_connection: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = discovery_connection["connection"]
    job = Job(
        kind="integrations.discover_resources",
        workspace_id=connection.owner_workspace_id,
        subject_type="integration_connection",
        subject_id=connection.id,
        content_hash="terminal-before-discovery",
        payload={},
        attempts=1,
        max_attempts=1,
    )
    db_session.add(job)
    await db_session.flush()
    handlers_module = import_module("services.integrations.discovery.handlers")

    async def fail_before_discovery(*args, **kwargs):
        raise RuntimeError("worker setup failed")

    monkeypatch.setattr(handlers_module, "run_discovery", fail_before_discovery)

    with pytest.raises(RuntimeError, match="worker setup failed"):
        await discover_resources(db_session, job)

    await db_session.refresh(connection)
    failed_run = await db_session.scalar(
        select(IntegrationDiscoveryRun).where(IntegrationDiscoveryRun.job_id == job.id)
    )
    assert connection.status == "error"
    assert failed_run is not None
    assert failed_run.status == "failed"
    assert failed_run.error_code == "RuntimeError"


async def test_handler_notifies_only_on_final_attempt(
    db_session: AsyncSession,
    discovery_connection: dict[str, object],
) -> None:
    connection = discovery_connection["connection"]
    provider = discovery_connection["provider"]
    provider["error"] = RuntimeError("still failing")
    job = Job(
        kind="integrations.discover_resources",
        workspace_id=connection.owner_workspace_id,
        subject_type="integration_connection",
        subject_id=connection.id,
        content_hash="handler-final-attempt",
        payload={},
        attempts=1,
        max_attempts=2,
    )
    db_session.add(job)
    await db_session.flush()

    with pytest.raises(RuntimeError):
        await discover_resources(db_session, job)
    count = await db_session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.notification_type == "integration_discovery_failed")
    )
    assert count == 0

    job.attempts = 2
    with pytest.raises(RuntimeError):
        await discover_resources(db_session, job)
    notes = list(
        (
            await db_session.scalars(
                select(Notification).where(
                    Notification.notification_type == "integration_discovery_failed"
                )
            )
        ).all()
    )
    assert len(notes) == 1
    assert notes[0].recipient_user_id == connection.connected_by_user_id
    generic_count = await db_session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.notification_type == "job_failed")
    )
    assert generic_count == 0


async def test_reference_auth_failure_uses_replacement_notification(
    db_session: AsyncSession,
    discovery_connection: dict[str, object],
) -> None:
    connection = discovery_connection["connection"]
    provider = discovery_connection["provider"]
    provider["error"] = IntegrationAuthError(
        "credential rejected",
        provider_key=connection.provider_key,
        operation="discover_resources",
    )
    job = Job(
        kind="integrations.discover_resources",
        workspace_id=connection.owner_workspace_id,
        subject_type="integration_connection",
        subject_id=connection.id,
        content_hash="handler-auth-failure",
        payload={},
        attempts=3,
        max_attempts=3,
    )
    db_session.add(job)
    await db_session.flush()

    with pytest.raises(IntegrationAuthError):
        await discover_resources(db_session, job)
    await db_session.refresh(connection)
    assert connection.status == "needs_credential"
    notification_types = set(
        (await db_session.scalars(select(Notification.notification_type))).all()
    )
    assert "integration_needs_credential" in notification_types
    assert "integration_needs_reauth" not in notification_types
    assert "integration_discovery_failed" not in notification_types


async def test_vault_unavailability_uses_terminal_discovery_notification(
    db_session: AsyncSession,
    discovery_connection: dict[str, object],
) -> None:
    connection = discovery_connection["connection"]
    provider = discovery_connection["provider"]
    provider["error"] = IntegrationCredentialUnavailableError(
        "Credential unavailable",
        provider_key="local",
        operation="resolve_secret",
    )
    job = Job(
        kind="integrations.discover_resources",
        workspace_id=connection.owner_workspace_id,
        subject_type="integration_connection",
        subject_id=connection.id,
        content_hash="handler-vault-failure",
        payload={},
        attempts=3,
        max_attempts=3,
    )
    db_session.add(job)
    await db_session.flush()

    with pytest.raises(IntegrationCredentialUnavailableError):
        await discover_resources(db_session, job)

    notification_types = set(
        (await db_session.scalars(select(Notification.notification_type))).all()
    )
    assert "integration_discovery_failed" in notification_types
    assert "integration_needs_credential" not in notification_types
    assert "integration_needs_reauth" not in notification_types


async def test_enqueued_discovery_executes_through_real_worker(
    committed_db_session_factory,
    discovery_provider: dict[str, object],
) -> None:
    from workers.job_runner import run_once

    user = build_user(email="discovery-worker@example.com")
    workspace = build_workspace(slug="discovery-worker")
    credential = build_external_credential(
        auth_mode="api_key",
        access_token_encrypted=None,
        secret_provider="local_env",  # noqa: S106 - inert test reference metadata
        secret_name="test-secret",  # noqa: S106 - inert test reference metadata
        secret_version="latest",  # noqa: S106 - inert test reference metadata
    )
    async with committed_db_session_factory() as setup:
        setup.add_all([user, workspace, credential])
        await setup.flush()
        connection = build_integration_connection(
            credential=credential,
            user=user,
            workspace=workspace,
            status="discovery_pending",
        )
        setup.add(connection)
        await setup.flush()
        job = await enqueue_discovery(setup, connection=connection)
        await setup.commit()
        user_id = user.id
        workspace_id = workspace.id
        credential_id = credential.id
        connection_id = connection.id
        job_id = job.id

    try:
        assert await run_once(owner_instance_id="discovery-test-worker") >= 1
        async with committed_db_session_factory() as verify:
            persisted_job = await verify.get(Job, job_id)
            assert persisted_job is not None
            assert persisted_job.status == "succeeded"
            resource = await verify.scalar(
                select(IntegrationResource).where(
                    IntegrationResource.connection_id == connection_id
                )
            )
            assert resource is not None
            assert resource.writable is True
    finally:
        async with committed_db_session_factory() as cleanup:
            await cleanup.execute(
                delete(Notification).where(Notification.recipient_user_id == user_id)
            )
            await cleanup.execute(delete(Job).where(Job.subject_id == connection_id))
            await cleanup.execute(
                delete(IntegrationConnection).where(IntegrationConnection.id == connection_id)
            )
            await cleanup.execute(
                delete(ExternalCredential).where(ExternalCredential.id == credential_id)
            )
            await cleanup.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await cleanup.execute(delete(User).where(User.id == user_id))
            await cleanup.commit()


async def test_terminal_worker_timeout_persists_failure_lifecycle(
    committed_db_session_factory,
    discovery_provider: dict[str, object],
) -> None:
    from workers.job_runner import run_once

    user = build_user(email="discovery-timeout@example.com")
    workspace = build_workspace(slug="discovery-timeout")
    credential = build_external_credential(
        auth_mode="api_key",
        access_token_encrypted=None,
        secret_provider="local_env",  # noqa: S106 - inert test reference metadata
        secret_name="test-secret",  # noqa: S106 - inert test reference metadata
        secret_version="latest",  # noqa: S106 - inert test reference metadata
    )
    async with committed_db_session_factory() as setup:
        setup.add_all([user, workspace, credential])
        await setup.flush()
        connection = build_integration_connection(
            credential=credential,
            user=user,
            workspace=workspace,
            status="discovery_pending",
        )
        setup.add(connection)
        await setup.flush()
        job = await enqueue_discovery(setup, connection=connection)
        job.max_attempts = 1
        await setup.commit()
        user_id = user.id
        workspace_id = workspace.id
        credential_id = credential.id
        connection_id = connection.id
        job_id = job.id

    definition = JOB_HANDLERS["integrations.discover_resources"]
    JOB_HANDLERS[definition.kind] = replace(definition, timeout=0.01)
    discovery_provider["block"] = True
    try:
        assert await run_once(owner_instance_id="discovery-timeout-worker") >= 1
        async with committed_db_session_factory() as verify:
            persisted_job = await verify.get(Job, job_id)
            persisted_connection = await verify.get(IntegrationConnection, connection_id)
            failed_run = await verify.scalar(
                select(IntegrationDiscoveryRun).where(
                    IntegrationDiscoveryRun.job_id == job_id,
                    IntegrationDiscoveryRun.status == "failed",
                )
            )
            notifications = list(
                (
                    await verify.scalars(
                        select(Notification).where(
                            Notification.notification_type == "integration_discovery_failed",
                            Notification.recipient_user_id == user_id,
                        )
                    )
                ).all()
            )
            assert persisted_job is not None
            assert persisted_job.status == "failed"
            assert persisted_job.last_error_code == "handler_timeout"
            assert persisted_connection is not None
            assert persisted_connection.status == "error"
            assert failed_run is not None
            assert failed_run.error_code == "handler_timeout"
            assert len(notifications) == 1
    finally:
        JOB_HANDLERS[definition.kind] = definition
        discovery_provider["block"] = False
        async with committed_db_session_factory() as cleanup:
            await cleanup.execute(
                delete(Notification).where(Notification.recipient_user_id == user_id)
            )
            await cleanup.execute(delete(Job).where(Job.subject_id == connection_id))
            await cleanup.execute(
                delete(IntegrationConnection).where(IntegrationConnection.id == connection_id)
            )
            await cleanup.execute(
                delete(ExternalCredential).where(ExternalCredential.id == credential_id)
            )
            await cleanup.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await cleanup.execute(delete(User).where(User.id == user_id))
            await cleanup.commit()
