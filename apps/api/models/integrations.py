# apps/api/models/integrations.py

"""Core persistence models for provider integrations and credentials."""

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from models.base import Base, BaseModel, TimestampMixin, UUIDMixin


class ExternalCredential(BaseModel):
    """Encrypted OAuth material or a reference to a provider-managed secret."""

    __tablename__ = "external_credentials"

    provider_key = Column(String(64), nullable=False, index=True)
    auth_mode = Column(String(32), nullable=False)
    access_token_encrypted = Column(Text, nullable=True)
    refresh_token_encrypted = Column(Text, nullable=True)
    token_expires_at = Column(DateTime(timezone=True), nullable=True)
    token_type = Column(String(32), nullable=True)
    granted_scopes = Column(JSONB, nullable=True)
    encryption_key_id = Column(String(16), nullable=True)
    secret_provider = Column(String(32), nullable=True)
    secret_name = Column(String(255), nullable=True)
    secret_version = Column(String(64), nullable=True)
    principal_fingerprint = Column(String(64), nullable=False, index=True)
    external_principal_label = Column(String(255), nullable=True)
    last_refreshed_at = Column(DateTime(timezone=True), nullable=True)
    refresh_failure_count = Column(Integer, nullable=False, default=0, server_default=text("0"))
    last_refresh_error_code = Column(String(64), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "auth_mode IN ('oauth', 'api_key', 'service_account', 'system_token')",
            name="ck_external_credentials_auth_mode",
        ),
        CheckConstraint(
            "(auth_mode = 'oauth' AND secret_provider IS NULL "
            "AND secret_name IS NULL AND secret_version IS NULL) OR "
            "(auth_mode <> 'oauth' AND access_token_encrypted IS NULL "
            "AND refresh_token_encrypted IS NULL AND secret_name IS NOT NULL "
            "AND secret_provider IS NOT NULL AND secret_version IS NOT NULL)",
            name="ck_external_credentials_mode_payload",
        ),
    )

    @property
    def access_token(self) -> str | None:
        if self.access_token_encrypted is None:
            return None
        from services.integrations.utils import decrypt_credential_token

        return decrypt_credential_token(self.access_token_encrypted)

    @access_token.setter
    def access_token(self, value: str | None) -> None:
        from services.integrations.utils import encrypt_credential_token

        self.access_token_encrypted = encrypt_credential_token(value) if value else None

    @property
    def refresh_token(self) -> str | None:
        if self.refresh_token_encrypted is None:
            return None
        from services.integrations.utils import decrypt_credential_token

        return decrypt_credential_token(self.refresh_token_encrypted)

    @refresh_token.setter
    def refresh_token(self, value: str | None) -> None:
        from services.integrations.utils import encrypt_credential_token

        self.refresh_token_encrypted = encrypt_credential_token(value) if value else None

    def crypto_shred(self) -> None:
        """Destroy locally held token material while retaining audit metadata."""
        self.access_token_encrypted = None
        self.refresh_token_encrypted = None
        self.encryption_key_id = None
        self.revoked_at = datetime.now(UTC)


class IntegrationConnection(BaseModel):
    """One labelled connection to an external provider principal."""

    __tablename__ = "integration_connections"

    provider_key = Column(String(64), nullable=False, index=True)
    label = Column(String(120), nullable=False)
    owner_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    owner_workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=True)
    credential_id = Column(
        UUID(as_uuid=True), ForeignKey("external_credentials.id"), nullable=False
    )
    status = Column(
        String(32), nullable=False, default="auth_pending", server_default=text("'auth_pending'")
    )
    status_reason = Column(Text, nullable=True)
    status_changed_at = Column(DateTime(timezone=True), nullable=True)
    connected_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    provider_metadata = Column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        CheckConstraint(
            "char_length(btrim(label)) > 0",
            name="ck_integration_connections_label_not_blank",
        ),
        CheckConstraint(
            "num_nonnulls(owner_user_id, owner_workspace_id) = 1",
            name="ck_integration_connections_owner_xor",
        ),
        CheckConstraint(
            "status IN ('auth_pending', 'discovery_pending', "
            "'needs_resource_selection', 'active', 'degraded', 'error', "
            "'revoked', 'needs_reauth')",
            name="ck_integration_connections_status",
        ),
        Index(
            "uq_integration_connections_credential",
            "credential_id",
            unique=True,
            postgresql_where=text("deleted = false"),
        ),
        # Multi-connection is intentional: owner/provider indexes are not unique.
        Index(
            "ix_integration_connections_workspace_provider",
            "owner_workspace_id",
            "provider_key",
            postgresql_where=text("deleted = false"),
        ),
        Index(
            "ix_integration_connections_user_provider",
            "owner_user_id",
            "provider_key",
            postgresql_where=text("deleted = false"),
        ),
    )


class IntegrationOAuthState(Base, TimestampMixin):
    """Single-use server-side state for an integration OAuth handshake."""

    __tablename__ = "integration_oauth_states"

    jti = Column(String(64), primary_key=True)
    connection_id = Column(
        UUID(as_uuid=True),
        ForeignKey("integration_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code_verifier_encrypted = Column(Text, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)


class IntegrationResource(BaseModel):
    """Provider resource discovered beneath an integration connection."""

    __tablename__ = "integration_resources"

    connection_id = Column(
        UUID(as_uuid=True),
        ForeignKey("integration_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    resource_type = Column(String(64), nullable=False)
    external_id = Column(String(255), nullable=False)
    display_name = Column(String(255), nullable=False)
    parent_external_id = Column(String(255), nullable=True)
    enabled = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    availability = Column(
        String(16), nullable=False, default="available", server_default=text("'available'")
    )
    writable = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    permissions_metadata = Column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    first_seen_at = Column(DateTime(timezone=True), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=False)
    removed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "availability IN ('available', 'unavailable', 'removed')",
            name="ck_integration_resources_availability",
        ),
        UniqueConstraint(
            "connection_id",
            "resource_type",
            "external_id",
            name="uq_integration_resources_connection_external",
        ),
        Index(
            "ix_integration_resources_connection_enabled",
            "connection_id",
            "enabled",
            postgresql_where=text("deleted = false"),
        ),
    )


class IntegrationDiscoveryRun(Base, UUIDMixin, TimestampMixin):
    """Append-mostly record of one provider resource-discovery attempt."""

    __tablename__ = "integration_discovery_runs"

    connection_id = Column(
        UUID(as_uuid=True),
        ForeignKey("integration_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id = Column(
        UUID(as_uuid=True),
        nullable=True,
        comment="No FK: discovery history outlives the jobs retention window.",
    )
    status = Column(String(16), nullable=False, default="running", server_default=text("'running'"))
    resources_found = Column(Integer, nullable=False, default=0, server_default=text("0"))
    resources_added = Column(Integer, nullable=False, default=0, server_default=text("0"))
    resources_removed = Column(Integer, nullable=False, default=0, server_default=text("0"))
    resources_unchanged = Column(Integer, nullable=False, default=0, server_default=text("0"))
    error_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    finished_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name="ck_integration_discovery_runs_status",
        ),
        Index("ix_integration_discovery_runs_connection_created", "connection_id", "created_at"),
    )
