# apps/api/models/classifiers.py

"""Workspace-owned classifier definitions."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from models.base import BaseModel


class Classifier(BaseModel):
    """One operator-authored closed-set classification tool."""

    __tablename__ = "classifiers"

    workspace_id = Column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String(48), nullable=False)
    display_name = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    instructions = Column(Text, nullable=True)
    labels = Column(JSONB, nullable=False)
    model_provider = Column(String(50), nullable=True)
    model = Column(String(100), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    owner_workspace = relationship("Workspace", foreign_keys=[workspace_id])
    creator = relationship("User", foreign_keys=[created_by])

    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_classifiers_workspace_name"),
        CheckConstraint(
            "(model_provider IS NULL) = (model IS NULL)",
            name="ck_classifiers_model_pair",
        ),
        Index("ix_classifiers_created_by", "created_by"),
        Index("ix_classifiers_workspace_updated", "workspace_id", "updated_at"),
        Index(
            "ix_classifiers_workspace_active",
            "workspace_id",
            postgresql_where=text("is_active = true AND deleted = false"),
        ),
    )
