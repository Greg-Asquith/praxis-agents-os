# apps/api/models/user.py

"""
Authentication and user-related models for the Praxis Agents OS application.

These models live in the public schema and handle:
- Users and password authentication
- Two-factor authentication
- Lockout management
- Password reset tokens
- User authentication records
- User roles
- User memberships
"""

import json
import secrets
from datetime import UTC, datetime

import pyotp
from sqlalchemy import (
    Boolean,
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
from sqlalchemy.dialects.postgresql import CITEXT, INET, JSONB, UUID
from sqlalchemy.orm import relationship

from core.exceptions.general import CustomValueError
from core.settings import settings
from models.base import BaseModel
from utils.security import (
    decrypt_data,
    encrypt_data,
    hash_password,
    hash_token,
    verify_password_hash,
    verify_token_hash,
)


class User(BaseModel):
    __tablename__ = "users"

    email = Column(CITEXT, unique=True, nullable=False, index=True)
    display_name = Column(String, nullable=True)
    avatar_url = Column(String, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False, server_default=text("true"))
    default_workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "workspaces.id",
            use_alter=True,
            name="fk_users_default_workspace_id_workspaces",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    # Password authentication fields
    password_hash = Column(String, nullable=True)
    password_changed_at = Column(DateTime(timezone=True), nullable=True)

    # Two-factor authentication fields
    totp_secret_encrypted = Column(Text, nullable=True)  # Encrypted TOTP secret
    totp_enabled = Column(Boolean, default=False, nullable=False, server_default=text("false"))
    totp_enabled_at = Column(DateTime(timezone=True), nullable=True)
    backup_codes_encrypted = Column(
        Text, nullable=True
    )  # Encrypted JSON array of hashed backup codes
    backup_codes_generated_at = Column(DateTime(timezone=True), nullable=True)

    # Security lockout fields
    failed_login_attempts = Column(Integer, default=0, nullable=False, server_default=text("0"))
    locked_until = Column(
        DateTime(timezone=True), nullable=True, index=True
    )  # Index for cleanup queries
    lockout_reason = Column(String, nullable=True)  # Reason for lockout

    # Relationships
    auth_records = relationship(
        "UserAuth",
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="UserAuth.user_id",
    )
    sessions = relationship(
        "Session",
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="Session.user_id",
    )
    workspace_memberships = relationship(
        "WorkspaceMembership",
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="WorkspaceMembership.user_id",
    )
    conversations = relationship(
        "Conversation",
        back_populates="owner",
        cascade="all, delete-orphan",
        foreign_keys="Conversation.user_id",
    )
    default_workspace = relationship("Workspace", foreign_keys=[default_workspace_id])

    def _cascade_soft_delete(self):
        """Soft delete related sessions and workspace memberships when user is deleted."""
        # Avoid circular imports; operate on loaded relationships
        for session in list(self.sessions or []):
            if not getattr(session, "is_deleted", False):
                session.soft_delete(cascade=False)
        for membership in list(self.workspace_memberships or []):
            if not getattr(membership, "is_deleted", False):
                membership.soft_delete(cascade=False)
        for auth in list(self.auth_records or []):
            if not getattr(auth, "is_deleted", False):
                auth.soft_delete(cascade=False)

    def _cascade_restore(self):
        """Restore related sessions and workspace memberships when user is restored."""
        for session in list(self.sessions or []):
            if getattr(session, "is_deleted", False):
                session.restore(cascade=False)
        for membership in list(self.workspace_memberships or []):
            if getattr(membership, "is_deleted", False):
                membership.restore(cascade=False)
        for auth in list(self.auth_records or []):
            if getattr(auth, "is_deleted", False):
                auth.restore(cascade=False)

    # Soft delete/restore overrides to manage active status
    def soft_delete(self, deleted_by=None, cascade=True):  # type: ignore[override]
        """Extend soft delete to also deactivate the user."""
        self.is_active = False
        super().soft_delete(deleted_by=deleted_by, cascade=cascade)

    def restore(self, cascade=True):  # type: ignore[override]
        """Extend restore to also re-activate the user."""
        super().restore(cascade=cascade)
        self.is_active = True

    # Password authentication methods
    def set_password(self, password: str) -> None:
        """Set user password with secure password hashing."""
        self.password_hash = hash_password(password)
        self.password_changed_at = datetime.now(UTC)

    def verify_password(self, password: str) -> bool:
        """Verify password against stored hash."""
        return verify_password_hash(password, self.password_hash)

    @property
    def has_password(self) -> bool:
        """Check if user has a password set."""
        return bool(self.password_hash)

    # TOTP/2FA methods
    def generate_totp_secret(self) -> str:
        """Generate and store encrypted TOTP secret."""
        # Generate a new TOTP secret
        secret = pyotp.random_base32()
        # Encrypt and store the secret
        self.totp_secret_encrypted = encrypt_data(secret)
        return secret

    def get_totp_secret(self) -> str | None:
        """Decrypt and return TOTP secret."""
        if not self.totp_secret_encrypted:
            return None
        return decrypt_data(self.totp_secret_encrypted)

    def enable_totp(self) -> None:
        """Enable TOTP authentication."""
        if not self.totp_secret_encrypted:
            raise CustomValueError(
                "TOTP secret must be generated first", details={"user_id": self.id}
            )
        self.totp_enabled = True
        self.totp_enabled_at = datetime.now(UTC)

    def disable_totp(self) -> None:
        """Disable TOTP authentication."""
        self.totp_enabled = False
        self.totp_enabled_at = None
        self.totp_secret_encrypted = None
        self.backup_codes_encrypted = None
        self.backup_codes_generated_at = None

    def verify_totp(self, token: str) -> bool:
        """Verify TOTP token using the stored secret.
        This should work during setup (before enabling) and after enablement.
        """
        if not self.totp_secret_encrypted:
            return False
        try:
            secret = self.get_totp_secret()
            if secret is None:
                return False
            totp = pyotp.TOTP(secret)
            # Verify token with 1-window tolerance (30 seconds before/after)
            return totp.verify(token, valid_window=1)
        except Exception:
            return False

    def get_totp_qr_uri(self, issuer_name: str | None = None) -> str:
        """Get TOTP QR code URI for authenticator apps."""
        if not self.totp_secret_encrypted:
            raise CustomValueError("TOTP secret not generated")
        secret = self.get_totp_secret()
        totp = pyotp.TOTP(secret)
        return totp.provisioning_uri(name=self.email, issuer_name=issuer_name or settings.APP_NAME)

    def generate_backup_codes(self) -> list[str]:
        """Generate backup codes for 2FA recovery."""
        # Generate 8 backup codes (8 digits each)
        backup_codes = []
        hashed_codes = []
        for _ in range(8):
            code = "".join([str(secrets.randbelow(10)) for _ in range(8)])
            backup_codes.append(code)
            hashed_codes.append(hash_password(code))
        # Store encrypted hashed codes
        self.backup_codes_encrypted = encrypt_data(json.dumps(hashed_codes))
        self.backup_codes_generated_at = datetime.now(UTC)
        return backup_codes  # Return unhashed codes to user (one-time only)

    def verify_backup_code(self, code: str) -> bool:
        """Verify and consume a backup code."""
        if not self.backup_codes_encrypted:
            return False
        try:
            # Decrypt and load hashed backup codes
            hashed_codes_json = decrypt_data(self.backup_codes_encrypted)
            hashed_codes = json.loads(hashed_codes_json)
            # Check against each backup code
            for i, hashed_code in enumerate(hashed_codes):
                if verify_password_hash(code, hashed_code):
                    # Remove used backup code
                    hashed_codes.pop(i)
                    # Update stored codes
                    if hashed_codes:
                        self.backup_codes_encrypted = encrypt_data(json.dumps(hashed_codes))
                    else:
                        # All codes used
                        self.backup_codes_encrypted = None
                        self.backup_codes_generated_at = None
                    return True
            return False
        except Exception as exc:
            raise CustomValueError(
                "Failed to verify backup code", details={"user_id": self.id}
            ) from exc

    @property
    def backup_codes_remaining(self) -> int:
        """Get number of remaining backup codes."""
        if not self.backup_codes_encrypted:
            return 0
        try:
            hashed_codes_json = decrypt_data(self.backup_codes_encrypted)
            hashed_codes = json.loads(hashed_codes_json)
            return len(hashed_codes)
        except Exception as exc:
            raise CustomValueError(
                "Failed to get backup codes remaining", details={"user_id": self.id}
            ) from exc

    @property
    def is_locked(self) -> bool:
        """Check if the user account is currently locked."""
        return self.locked_until is not None and self.locked_until > datetime.now(UTC)

    __table_args__ = (
        Index("ix_users_default_workspace", "default_workspace_id"),  # For workspace switching
    )


class PasswordResetToken(BaseModel):
    """Password reset tokens for secure password recovery."""

    __tablename__ = "password_reset_tokens"

    token = Column(String, unique=True, nullable=False, index=True)  # SHA256 hash of reset token
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    used_at = Column(DateTime(timezone=True), nullable=True)  # Track when token was used
    ip_address = Column(INET, nullable=True)  # Track requesting IP
    user_agent = Column(Text, nullable=True)  # Track requesting user agent

    # Relationship
    user = relationship("User", foreign_keys=[user_id])

    @property
    def is_expired(self) -> bool:
        """Check if the token has expired."""
        return datetime.now(UTC) > self.expires_at

    @property
    def is_used(self) -> bool:
        """Check if the token has been used."""
        return self.used_at is not None

    @property
    def is_valid(self) -> bool:
        """Check if the token is valid (not expired and not used)."""
        return not self.is_expired and not self.is_used

    def mark_as_used(self) -> None:
        """Mark the token as used."""
        self.used_at = datetime.now(UTC)

    @classmethod
    def generate_token(cls) -> str:
        """Generate a secure random token."""
        return secrets.token_urlsafe(32)

    @classmethod
    def hash_raw_token(cls, raw_token: str) -> str:
        """Hash a raw reset token for secure at-rest storage."""
        return hash_token(raw_token)

    def verify_raw_token(self, raw_token: str) -> bool:
        """Constant-time verification of raw token against stored hash."""
        return verify_token_hash(raw_token, self.token)

    def __repr__(self):
        return f"<PasswordResetToken {self.token[:8]}... user={self.user_id} valid={self.is_valid}>"

    __table_args__ = (
        Index("ix_password_reset_user_expires", "user_id", "expires_at"),  # Cleanup queries
        Index("ix_password_reset_expires_used", "expires_at", "used_at"),  # Token validation
    )


class UserAuth(BaseModel):
    __tablename__ = "user_auth"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    provider = Column(String, nullable=False)  # 'google', 'github', etc.
    provider_user_id = Column(String, nullable=False)
    email = Column(CITEXT, nullable=False)
    email_verified = Column(Boolean, default=False, nullable=False, server_default=text("false"))
    access_token_encrypted = Column(Text, nullable=True)  # Encrypted access token
    refresh_token_encrypted = Column(Text, nullable=True)  # Encrypted refresh token
    token_expires_at = Column(DateTime(timezone=True), nullable=True)
    raw_profile = Column(JSONB, nullable=True)  # Raw profile data from OAuth provider

    # Relationships
    user = relationship("User", back_populates="auth_records", foreign_keys=[user_id])

    # Convenience properties for encrypted token handling
    @property
    def access_token(self):
        """Get decrypted access token"""
        if not self.access_token_encrypted:
            return None
        return decrypt_data(self.access_token_encrypted)

    @access_token.setter
    def access_token(self, value):
        """Set encrypted access token"""
        if value is None:
            self.access_token_encrypted = None
        else:
            self.access_token_encrypted = encrypt_data(value)

    @property
    def refresh_token(self):
        """Get decrypted refresh token"""
        if not self.refresh_token_encrypted:
            return None
        return decrypt_data(self.refresh_token_encrypted)

    @refresh_token.setter
    def refresh_token(self, value):
        """Set encrypted refresh token"""
        if value is None:
            self.refresh_token_encrypted = None
        else:
            self.refresh_token_encrypted = encrypt_data(value)

    @property
    def is_token_expired(self) -> bool:
        """Check if the OAuth token is expired"""
        if not self.token_expires_at:
            # If no expiry time, assume token doesn't expire (like GitHub)
            return False
        return datetime.now(UTC) >= self.token_expires_at

    # Unique constraint
    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_user_id", name="uq_user_auth_provider_provider_user_id"
        ),
        Index("ix_user_auth_user_provider", "user_id", "provider"),  # User's auth methods
        Index("ix_user_auth_email_provider", "email", "provider"),  # OAuth login lookup
        Index("ix_user_auth_token_expires", "token_expires_at"),  # Token refresh queries
    )
