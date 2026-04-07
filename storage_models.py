"""SQLAlchemy models for the bearer-service storage layer."""

from __future__ import annotations
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bearer_token_manager import build_token_prefix, hash_bearer_token, verify_bearer_token
from secret_manager import decrypt_secret_payload, encrypt_secret_payload
from storage import Base
from token_scopes import (
    TOKEN_ACCESS_POLICY_VERSION,
    deserialize_token_scopes,
    serialize_token_scopes,
)

ACCOUNT_STATUS_ACTIVE = "active"
ACCOUNT_STATUSES = (ACCOUNT_STATUS_ACTIVE,)

CONNECTION_STATUS_ACTIVE = "active"
CONNECTION_STATUS_DISABLED = "disabled"
CONNECTION_STATUSES = (CONNECTION_STATUS_ACTIVE, CONNECTION_STATUS_DISABLED)

TOKEN_STATUS_ACTIVE = "active"
TOKEN_STATUS_REVOKED = "revoked"
TOKEN_STATUS_EXPIRED = "expired"
TOKEN_STATUS_DISABLED = "disabled"
TOKEN_STATUSES = (TOKEN_STATUS_ACTIVE, TOKEN_STATUS_REVOKED, TOKEN_STATUS_EXPIRED, TOKEN_STATUS_DISABLED)


class Account(Base):
    """Service account owning a Vetmanager connection and bearer tokens."""

    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in ACCOUNT_STATUSES)})",
            name="ck_accounts_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    vetmanager_connections: Mapped[list["VetmanagerConnection"]] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
    )
    bearer_tokens: Mapped[list["ServiceBearerToken"]] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
    )


class VetmanagerConnection(Base):
    """Stored Vetmanager auth configuration for one service account."""

    __tablename__ = "vetmanager_connections"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in CONNECTION_STATUSES)})",
            name="ck_vetmanager_connections_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    auth_mode: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    domain: Mapped[str | None] = mapped_column(String(128), nullable=True)
    encrypted_credentials: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    account: Mapped[Account] = relationship(back_populates="vetmanager_connections")

    def set_credentials(self, payload: dict[str, str], *, encryption_key: str | None = None) -> None:
        """Persist Vetmanager credentials in encrypted form only."""
        self.encrypted_credentials = encrypt_secret_payload(payload, key=encryption_key)

    def get_credentials(self, *, encryption_key: str | None = None) -> dict[str, str] | None:
        """Return decrypted Vetmanager credentials if present."""
        if not self.encrypted_credentials:
            return None
        return decrypt_secret_payload(self.encrypted_credentials, key=encryption_key)


class ServiceBearerToken(Base):
    """Stored bearer token metadata; raw token must never be persisted."""

    __tablename__ = "service_bearer_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_service_bearer_tokens_token_hash"),
        UniqueConstraint("token_prefix", name="uq_service_bearer_tokens_token_prefix"),
        CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in TOKEN_STATUSES)})",
            name="ck_service_bearer_tokens_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    token_prefix: Mapped[str] = mapped_column(String(32), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    access_policy_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=TOKEN_ACCESS_POLICY_VERSION,
        server_default="1",
    )
    scopes_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    allowed_ip_mask: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    account: Mapped[Account] = relationship(back_populates="bearer_tokens")
    usage_stats: Mapped["TokenUsageStat | None"] = relationship(
        back_populates="bearer_token",
        cascade="all, delete-orphan",
        uselist=False,
    )
    usage_logs: Mapped[list["TokenUsageLog"]] = relationship(
        back_populates="bearer_token",
        cascade="all, delete-orphan",
    )

    def set_raw_token(self, raw_token: str) -> None:
        """Persist only token hash and safe prefix derived from raw token."""
        self.token_prefix = build_token_prefix(raw_token)
        self.token_hash = hash_bearer_token(raw_token)

    def verify_raw_token(self, raw_token: str) -> bool:
        """Verify raw bearer token against stored deterministic hash."""
        return verify_bearer_token(raw_token, self.token_hash)

    def set_scopes(self, scopes: list[str] | tuple[str, ...] | None) -> None:
        """Persist stable validated scope manifest for this token."""
        self.access_policy_version = TOKEN_ACCESS_POLICY_VERSION
        self.scopes_json = serialize_token_scopes(scopes)

    def get_scopes(self) -> list[str]:
        """Return scope manifest, falling back to legacy full-access policy."""
        return deserialize_token_scopes(self.scopes_json)

    def get_allowed_ip_mask(self) -> str:
        """Return effective IP mask, defaulting to unrestricted."""
        return self.allowed_ip_mask or "*.*.*.*"

    def is_revoked(self) -> bool:
        """Return True when token has already been revoked."""
        return self.status == TOKEN_STATUS_REVOKED or self.revoked_at is not None

    def is_expired(self, *, now: datetime | None = None) -> bool:
        """Return True when expiry timestamp is in the past."""
        if self.expires_at is None:
            return False
        current_time = now or datetime.now(timezone.utc)
        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at <= current_time

    def sync_status(self, *, now: datetime | None = None) -> str:
        """Synchronize derived token status from revoke/expiry state."""
        if self.is_revoked():
            self.status = TOKEN_STATUS_REVOKED
            return self.status
        if self.is_expired(now=now):
            self.status = TOKEN_STATUS_EXPIRED
            return self.status
        return self.status

    def is_active(self, *, now: datetime | None = None) -> bool:
        """Return True only for non-expired, non-revoked active tokens."""
        return self.sync_status(now=now) == TOKEN_STATUS_ACTIVE

    def revoke(self, *, revoked_at: datetime | None = None) -> None:
        """Revoke token immediately and persist revoke timestamp."""
        self.revoked_at = revoked_at or datetime.now(timezone.utc)
        self.status = TOKEN_STATUS_REVOKED

    def mark_used(self, *, used_at: datetime | None = None) -> None:
        """Stamp last usage time for active token accounting."""
        self.last_used_at = used_at or datetime.now(timezone.utc)


class TokenUsageStat(Base):
    """Aggregated usage counters for one bearer token."""

    __tablename__ = "token_usage_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bearer_token_id: Mapped[int] = mapped_column(
        ForeignKey("service_bearer_tokens.id"),
        nullable=False,
        unique=True,
    )
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    bearer_token: Mapped[ServiceBearerToken] = relationship(back_populates="usage_stats")


class TokenUsageLog(Base):
    """Detailed audit log of bearer-token lifecycle and usage events."""

    __tablename__ = "token_usage_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bearer_token_id: Mapped[int] = mapped_column(
        ForeignKey("service_bearer_tokens.id"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    event_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    details_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    bearer_token: Mapped[ServiceBearerToken] = relationship(back_populates="usage_logs")
