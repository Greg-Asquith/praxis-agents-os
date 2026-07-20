"""Integration retention sweep boundaries."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.audit_event import AuditEvent
from models.integrations import (
    ExternalCredential,
    IntegrationConnection,
    IntegrationDiscoveryRun,
    IntegrationOAuthState,
    IntegrationResource,
)
from models.jobs import Job
from services.audit_events import AuditAction, AuditResourceType
from services.integrations.discovery.sweep_stale import sweep_stale
from services.integrations.utils import record_integration_audit
from tests.factories import (
    build_external_credential,
    build_integration_connection,
    build_integration_discovery_run,
    build_integration_resource,
)


async def test_sweep_deletes_expired_history_and_removed_resources(
    db_session: AsyncSession,
    discovery_connection: dict[str, object],
) -> None:
    connection = discovery_connection["connection"]
    now = datetime.now(UTC)
    old_run = build_integration_discovery_run(connection=connection)
    fresh_run = build_integration_discovery_run(connection=connection)
    old_resource = build_integration_resource(
        connection=connection,
        external_id="old",
        availability="removed",
        removed_at=now - timedelta(days=91),
    )
    fresh_resource = build_integration_resource(
        connection=connection,
        external_id="fresh",
        availability="removed",
        removed_at=now - timedelta(days=89),
    )
    job = Job(
        kind="integrations.sweep_stale",
        content_hash="sweep-test",
        payload={},
        attempts=1,
        max_attempts=5,
    )
    db_session.add_all([old_run, fresh_run, old_resource, fresh_resource, job])
    await db_session.flush()
    await db_session.execute(
        IntegrationDiscoveryRun.__table__.update()
        .where(IntegrationDiscoveryRun.id == old_run.id)
        .values(created_at=now - timedelta(days=91))
    )
    await db_session.execute(
        IntegrationDiscoveryRun.__table__.update()
        .where(IntegrationDiscoveryRun.id == fresh_run.id)
        .values(created_at=now - timedelta(days=89))
    )

    await sweep_stale(db_session, job=job)
    old_run_count = await db_session.scalar(
        select(func.count())
        .select_from(IntegrationDiscoveryRun)
        .where(IntegrationDiscoveryRun.id == old_run.id)
    )
    fresh_run_count = await db_session.scalar(
        select(func.count())
        .select_from(IntegrationDiscoveryRun)
        .where(IntegrationDiscoveryRun.id == fresh_run.id)
    )
    old_resource_count = await db_session.scalar(
        select(func.count())
        .select_from(IntegrationResource)
        .where(IntegrationResource.id == old_resource.id)
    )
    fresh_resource_count = await db_session.scalar(
        select(func.count())
        .select_from(IntegrationResource)
        .where(IntegrationResource.id == fresh_resource.id)
    )
    assert old_run_count == 0
    assert fresh_run_count == 1
    assert old_resource_count == 0
    assert fresh_resource_count == 1
    next_job = await db_session.scalar(
        select(Job).where(
            Job.kind == "integrations.sweep_stale",
            Job.id != job.id,
        )
    )
    assert next_job is not None


async def test_sweep_enforces_revoked_auth_pending_and_oauth_state_boundaries(
    db_session: AsyncSession,
    discovery_connection: dict[str, object],
) -> None:
    user = discovery_connection["user"]
    workspace = discovery_connection["workspace"]
    retained_connection = discovery_connection["connection"]
    now = datetime.now(UTC)

    credentials = [
        build_external_credential(
            provider_key="test_provider",
            auth_mode="api_key",
            access_token_encrypted=None,
            secret_provider="local_env",  # noqa: S106 - inert test reference metadata
            secret_name=f"test-{index}",
            secret_version="latest",  # noqa: S106 - inert test reference metadata
            principal_fingerprint=f"{index + 1:064x}",
            revoked_at=revoked_at,
        )
        for index, revoked_at in enumerate(
            (now - timedelta(days=31), now - timedelta(days=29), None)
        )
    ]
    db_session.add_all(credentials)
    await db_session.flush()
    old_revoked = build_integration_connection(
        credential=credentials[0],
        user=user,
        workspace=workspace,
        status="revoked",
        label="Old revoked",
    )
    fresh_revoked = build_integration_connection(
        credential=credentials[1],
        user=user,
        workspace=workspace,
        status="revoked",
        label="Fresh revoked",
    )
    stale_auth = build_integration_connection(
        credential=credentials[2],
        user=user,
        workspace=workspace,
        status="auth_pending",
        label="Stale auth",
    )
    expired_state = IntegrationOAuthState(
        jti=uuid4().hex,
        connection_id=retained_connection.id,
        code_verifier_encrypted="expired",
        expires_at=now - timedelta(seconds=1),
    )
    fresh_state = IntegrationOAuthState(
        jti=uuid4().hex,
        connection_id=retained_connection.id,
        code_verifier_encrypted="fresh",
        expires_at=now + timedelta(minutes=1),
    )
    job = Job(
        kind="integrations.sweep_stale",
        content_hash="sweep-lifecycle-test",
        payload={},
        attempts=1,
        max_attempts=5,
    )
    db_session.add_all([old_revoked, fresh_revoked, stale_auth, expired_state, fresh_state, job])
    await db_session.flush()
    await record_integration_audit(
        db_session,
        workspace_id=workspace.id,
        action=AuditAction.DELETE,
        resource_type=AuditResourceType.INTEGRATION_CONNECTION,
        resource_id=old_revoked.id,
        details={"retention_test": True},
    )
    await db_session.execute(
        IntegrationConnection.__table__.update()
        .where(IntegrationConnection.id == stale_auth.id)
        .values(created_at=now - timedelta(days=8))
    )

    await sweep_stale(db_session, job=job)
    remaining_connection_ids = set(
        (
            await db_session.scalars(
                select(IntegrationConnection.id).where(
                    IntegrationConnection.id.in_([old_revoked.id, fresh_revoked.id, stale_auth.id])
                )
            )
        ).all()
    )
    remaining_credential_ids = set(
        (
            await db_session.scalars(
                select(ExternalCredential.id).where(
                    ExternalCredential.id.in_([credential.id for credential in credentials])
                )
            )
        ).all()
    )
    assert remaining_connection_ids == {fresh_revoked.id}
    assert remaining_credential_ids == {credentials[1].id}
    surviving_audit = await db_session.scalar(
        select(AuditEvent.id).where(AuditEvent.resource_id == str(old_revoked.id))
    )
    assert surviving_audit is not None
    assert await db_session.get(IntegrationOAuthState, expired_state.jti) is None
    assert await db_session.get(IntegrationOAuthState, fresh_state.jti) is not None
