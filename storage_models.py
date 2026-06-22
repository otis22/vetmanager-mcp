"""SQLAlchemy models for the bearer-service storage layer."""

from __future__ import annotations
from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
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

OAUTH_STATUS_ACTIVE = "active"
OAUTH_STATUS_DISABLED = "disabled"
OAUTH_STATUS_REVOKED = "revoked"
OAUTH_STATUS_EXPIRED = "expired"
OAUTH_STATUS_CONSUMED = "consumed"

OAUTH_CLIENT_STATUSES = (OAUTH_STATUS_ACTIVE, OAUTH_STATUS_DISABLED)
OAUTH_GRANT_STATUSES = (OAUTH_STATUS_ACTIVE, OAUTH_STATUS_REVOKED)
OAUTH_CODE_STATUSES = (OAUTH_STATUS_ACTIVE, OAUTH_STATUS_CONSUMED, OAUTH_STATUS_EXPIRED)
OAUTH_TOKEN_STATUSES = (OAUTH_STATUS_ACTIVE, OAUTH_STATUS_REVOKED, OAUTH_STATUS_EXPIRED)

TOKEN_STATUS_ACTIVE = "active"
TOKEN_STATUS_REVOKED = "revoked"
TOKEN_STATUS_EXPIRED = "expired"
TOKEN_STATUS_DISABLED = "disabled"
TOKEN_STATUSES = (TOKEN_STATUS_ACTIVE, TOKEN_STATUS_REVOKED, TOKEN_STATUS_EXPIRED, TOKEN_STATUS_DISABLED)

FEEDBACK_SOURCE_MODEL = "model"
FEEDBACK_SOURCE_AUTO = "auto"
FEEDBACK_SOURCE_USER_COMPLAINT = "user_complaint"
FEEDBACK_SOURCES = (
    FEEDBACK_SOURCE_MODEL,
    FEEDBACK_SOURCE_AUTO,
    FEEDBACK_SOURCE_USER_COMPLAINT,
)

FEEDBACK_CATEGORY_BUG = "bug"
FEEDBACK_CATEGORY_MISSING_TOOL = "missing_tool"
FEEDBACK_CATEGORY_BAD_DESCRIPTION = "bad_description"
FEEDBACK_CATEGORY_CONTRACT = "contract"
FEEDBACK_CATEGORY_PERF = "perf"
FEEDBACK_CATEGORY_DOCS = "docs"
FEEDBACK_CATEGORY_OTHER = "other"
FEEDBACK_CATEGORIES = (
    FEEDBACK_CATEGORY_BUG,
    FEEDBACK_CATEGORY_MISSING_TOOL,
    FEEDBACK_CATEGORY_BAD_DESCRIPTION,
    FEEDBACK_CATEGORY_CONTRACT,
    FEEDBACK_CATEGORY_PERF,
    FEEDBACK_CATEGORY_DOCS,
    FEEDBACK_CATEGORY_OTHER,
)

FEEDBACK_SEVERITY_LOW = "low"
FEEDBACK_SEVERITY_MEDIUM = "medium"
FEEDBACK_SEVERITY_HIGH = "high"
FEEDBACK_SEVERITIES = (
    FEEDBACK_SEVERITY_LOW,
    FEEDBACK_SEVERITY_MEDIUM,
    FEEDBACK_SEVERITY_HIGH,
)

FEEDBACK_STATUS_NEW = "new"
FEEDBACK_STATUS_GROUPED = "grouped"
FEEDBACK_STATUS_TRIAGED = "triaged"
FEEDBACK_STATUS_LINKED = "linked"
FEEDBACK_STATUS_IGNORED = "ignored"
FEEDBACK_STATUSES = (
    FEEDBACK_STATUS_NEW,
    FEEDBACK_STATUS_GROUPED,
    FEEDBACK_STATUS_TRIAGED,
    FEEDBACK_STATUS_LINKED,
    FEEDBACK_STATUS_IGNORED,
)

KNOWN_ISSUE_STATUS_OPEN = "open"
KNOWN_ISSUE_STATUS_ACKNOWLEDGED = "acknowledged"
KNOWN_ISSUE_STATUS_WORKAROUND_AVAILABLE = "workaround_available"
KNOWN_ISSUE_STATUS_FIXED = "fixed"
KNOWN_ISSUE_STATUS_WONTFIX = "wontfix"
KNOWN_ISSUE_STATUSES = (
    KNOWN_ISSUE_STATUS_OPEN,
    KNOWN_ISSUE_STATUS_ACKNOWLEDGED,
    KNOWN_ISSUE_STATUS_WORKAROUND_AVAILABLE,
    KNOWN_ISSUE_STATUS_FIXED,
    KNOWN_ISSUE_STATUS_WONTFIX,
)


class Account(Base):
    """Service account owning a Vetmanager connection and bearer tokens."""

    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in ACCOUNT_STATUSES)})",
            name="ck_accounts_status",
        ),
        Index("ix_accounts_archived_at", "archived_at"),
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
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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
    is_depersonalized: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    # Stage 155: NOT NULL — wildcard ('*.*.*.*') stored explicitly; no
    # implicit "NULL means unrestricted" fallback in production code.
    # Web flow requires explicit user confirmation for wildcard issuance.
    # Python-side default exists only to keep ORM-direct test fixtures
    # green; the production write path (`issue_service_bearer_token`)
    # makes `ip_mask` a required argument with no default — see AC #3.
    allowed_ip_mask: Mapped[str] = mapped_column(
        String(64), nullable=False, default="*.*.*.*",
    )
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
    __table_args__ = (
        Index(
            "ix_token_usage_logs_event_type_event_at",
            "event_type",
            "event_at",
        ),
    )

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


class OAuthClient(Base):
    """Dynamic OAuth public client registered by ChatGPT."""

    __tablename__ = "oauth_clients"
    __table_args__ = (
        UniqueConstraint("client_id", name="uq_oauth_clients_client_id"),
        CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in OAUTH_CLIENT_STATUSES)})",
            name="ck_oauth_clients_status",
        ),
        Index("ix_oauth_clients_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(96), nullable=False)
    client_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    redirect_uris_json: Mapped[str] = mapped_column(Text, nullable=False)
    token_endpoint_auth_method: Mapped[str] = mapped_column(String(32), nullable=False)
    grant_types_json: Mapped[str] = mapped_column(Text, nullable=False)
    response_types_json: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=OAUTH_STATUS_ACTIVE)
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
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OAuthGrant(Base):
    """Authorized ChatGPT grant bound to one Vetmanager connection."""

    __tablename__ = "oauth_grants"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in OAUTH_GRANT_STATUSES)})",
            name="ck_oauth_grants_status",
        ),
        Index("ix_oauth_grants_account_status", "account_id", "status"),
        Index("ix_oauth_grants_connection_status", "vetmanager_connection_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    vetmanager_connection_id: Mapped[int] = mapped_column(
        ForeignKey("vetmanager_connections.id"),
        nullable=False,
        index=True,
    )
    client_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    scopes_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=OAUTH_STATUS_ACTIVE)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)


class OAuthAuthorizationCode(Base):
    """Single-use OAuth authorization code stored as hash-at-rest."""

    __tablename__ = "oauth_authorization_codes"
    __table_args__ = (
        UniqueConstraint("code_hash", name="uq_oauth_authorization_codes_code_hash"),
        CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in OAUTH_CODE_STATUSES)})",
            name="ck_oauth_authorization_codes_status",
        ),
        Index("ix_oauth_authorization_codes_client_status", "client_id", "status"),
        Index("ix_oauth_authorization_codes_expires", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code_prefix: Mapped[str] = mapped_column(String(32), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    client_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    redirect_uri: Mapped[str] = mapped_column(Text, nullable=False)
    resource: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    code_challenge: Mapped[str] = mapped_column(String(160), nullable=False)
    code_challenge_method: Mapped[str] = mapped_column(String(16), nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    vetmanager_connection_id: Mapped[int] = mapped_column(
        ForeignKey("vetmanager_connections.id"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=OAUTH_STATUS_ACTIVE)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class OAuthAccessToken(Base):
    """OAuth access token metadata; raw token is returned once and never stored."""

    __tablename__ = "oauth_access_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_oauth_access_tokens_token_hash"),
        CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in OAUTH_TOKEN_STATUSES)})",
            name="ck_oauth_access_tokens_status",
        ),
        Index("ix_oauth_access_tokens_grant_status", "grant_id", "status"),
        Index("ix_oauth_access_tokens_expires", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    grant_id: Mapped[int] = mapped_column(ForeignKey("oauth_grants.id"), nullable=False, index=True)
    token_prefix: Mapped[str] = mapped_column(String(32), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    resource: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=OAUTH_STATUS_ACTIVE)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class OAuthRefreshToken(Base):
    """Rotating OAuth refresh token stored as hash-at-rest."""

    __tablename__ = "oauth_refresh_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_oauth_refresh_tokens_token_hash"),
        CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in OAUTH_TOKEN_STATUSES)})",
            name="ck_oauth_refresh_tokens_status",
        ),
        Index("ix_oauth_refresh_tokens_grant_status", "grant_id", "status"),
        Index("ix_oauth_refresh_tokens_expires", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    grant_id: Mapped[int] = mapped_column(ForeignKey("oauth_grants.id"), nullable=False, index=True)
    token_prefix: Mapped[str] = mapped_column(String(32), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    resource: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=OAUTH_STATUS_ACTIVE)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_token_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class AgentFeedbackReport(Base):
    """Untrusted agent/user feedback stored after strict redaction."""

    __tablename__ = "agent_feedback_reports"
    __table_args__ = (
        CheckConstraint(
            f"source IN ({', '.join(repr(s) for s in FEEDBACK_SOURCES)})",
            name="ck_agent_feedback_reports_source",
        ),
        CheckConstraint(
            f"category IN ({', '.join(repr(s) for s in FEEDBACK_CATEGORIES)})",
            name="ck_agent_feedback_reports_category",
        ),
        CheckConstraint(
            f"severity IN ({', '.join(repr(s) for s in FEEDBACK_SEVERITIES)})",
            name="ck_agent_feedback_reports_severity",
        ),
        CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in FEEDBACK_STATUSES)})",
            name="ck_agent_feedback_reports_status",
        ),
        Index(
            "ix_agent_feedback_reports_tool_fingerprint",
            "related_tool",
            "error_fingerprint_hash",
        ),
        Index(
            "ix_agent_feedback_reports_status_created",
            "status",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
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
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=FEEDBACK_STATUS_NEW)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True, index=True)
    bearer_token_id: Mapped[int | None] = mapped_column(
        ForeignKey("service_bearer_tokens.id"),
        nullable=True,
        index=True,
    )
    related_tool: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    related_call_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    params_shape_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str] = mapped_column(String(240), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_fix: Mapped[str | None] = mapped_column(Text, nullable=True)
    reproduce: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_fingerprint_hash: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    known_issue_id: Mapped[int | None] = mapped_column(ForeignKey("known_issues.id"), nullable=True)
    duplicate_of_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_feedback_reports.id"),
        nullable=True,
    )
    redaction_version: Mapped[int] = mapped_column(Integer, nullable=False, default=2, server_default="2")
    possible_pii: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")


class KnownIssue(Base):
    """Operator-verified issue that may expose a deterministic agent playbook."""

    __tablename__ = "known_issues"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in KNOWN_ISSUE_STATUSES)})",
            name="ck_known_issues_status",
        ),
        CheckConstraint(
            f"category IN ({', '.join(repr(s) for s in FEEDBACK_CATEGORIES)})",
            name="ck_known_issues_category",
        ),
        CheckConstraint(
            f"severity IN ({', '.join(repr(s) for s in FEEDBACK_SEVERITIES)})",
            name="ck_known_issues_severity",
        ),
        Index(
            "ix_known_issues_tool_fingerprint",
            "related_tool",
            "error_fingerprint_hash",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
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
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100, server_default="100")
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    related_tool: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    error_fingerprint_hash: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    match_rules_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_playbook_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    public_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    workaround: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    fixed_in_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    report_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# Stage 151: persistent log of every known-issue match — broader source-of-truth
# than agent_feedback_reports.known_issue_id (which is gated by dedup/cap).
KNOWN_ISSUE_MATCH_SOURCES = ("injection", "report", "auto")


class KnownIssueMatchEvent(Base):
    """Privacy-safe analytics row: one per known-issue match (no raw payload)."""

    __tablename__ = "known_issue_match_events"
    __table_args__ = (
        # Hardcoded literal kept in sync with KNOWN_ISSUE_MATCH_SOURCES via
        # CHECK definition mirrored in alembic/versions/20260502_000012.
        CheckConstraint(
            "source IN ('injection', 'report', 'auto')",
            name="ck_known_issue_match_events_source",
        ),
        Index(
            "ix_known_issue_match_events_known_issue_created",
            "known_issue_id",
            "created_at",
        ),
        Index(
            "ix_known_issue_match_events_account_created",
            "account_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    known_issue_id: Mapped[int] = mapped_column(
        ForeignKey("known_issues.id", ondelete="CASCADE"),
        nullable=False,
    )
    related_tool: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_fingerprint_hash: Mapped[str | None] = mapped_column(String(96), nullable=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    bearer_token_id: Mapped[int | None] = mapped_column(
        ForeignKey("service_bearer_tokens.id", ondelete="SET NULL"),
        nullable=True,
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False)
