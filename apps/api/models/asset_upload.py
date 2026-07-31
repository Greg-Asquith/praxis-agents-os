# apps/api/models/asset_upload.py

"""Ephemeral grants for replay-safe managed asset uploads."""

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID

from models.base import Base, CreatedAtMixin, UUIDMixin


class AssetUpload(Base, UUIDMixin, CreatedAtMixin):
    """Persisted confirmation state for public assets and skill documents."""

    __tablename__ = "asset_uploads"

    token_id = Column(String(128), nullable=False)
    kind = Column(String(32), nullable=False)
    object_key = Column(String(1024), nullable=False)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    target_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("token_id", name="uq_asset_uploads_token_id"),
        UniqueConstraint("object_key", name="uq_asset_uploads_object_key"),
        Index(
            "ix_asset_uploads_pending_expiry",
            "expires_at",
            postgresql_where=text("consumed_at IS NULL"),
        ),
    )
