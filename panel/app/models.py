import secrets
import uuid as uuidlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .config import settings
from .db import Base
from .reality import generate_keypair


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _token(n: int = 16) -> str:
    return secrets.token_urlsafe(n)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), unique=True, default=lambda: str(uuidlib.uuid4()))
    sub_token: Mapped[str] = mapped_column(String(64), unique=True, index=True, default=_token)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str] = mapped_column(String(128), default="")
    note: Mapped[str] = mapped_column(Text, default="")

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)  # None = never expires
    traffic_limit: Mapped[int] = mapped_column(BigInteger, default=0)  # bytes, 0 = unlimited
    used_up: Mapped[int] = mapped_column(BigInteger, default=0)
    used_down: Mapped[int] = mapped_column(BigInteger, default=0)

    trial_used: Mapped[bool] = mapped_column(Boolean, default=False)
    referred_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    referral_rewarded: Mapped[bool] = mapped_column(Boolean, default=False)
    reminded_for: Mapped[datetime | None] = mapped_column(DateTime)  # expires_at we last warned about
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    payments: Mapped[list["Payment"]] = relationship(back_populates="user", cascade="all, delete-orphan")

    @property
    def email(self) -> str:
        """Identifier used inside Xray configs and traffic stats."""
        return f"u{self.id}"

    @property
    def used_total(self) -> int:
        return self.used_up + self.used_down

    def is_active(self, now: datetime | None = None) -> bool:
        now = now or utcnow()
        if not self.enabled:
            return False
        if self.expires_at is not None and self.expires_at <= now:
            return False
        if self.traffic_limit and self.used_total >= self.traffic_limit:
            return False
        return True

    def extend(self, days: int) -> None:
        """Add days on top of the remaining time (or from now if already expired)."""
        base = self.expires_at if self.expires_at and self.expires_at > utcnow() else utcnow()
        self.expires_at = base + timedelta(days=days)
        self.enabled = True


class Node(Base):
    __tablename__ = "nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    flag: Mapped[str] = mapped_column(String(16), default="🌐")
    address: Mapped[str] = mapped_column(String(255))  # public IP or domain clients connect to
    port: Mapped[int] = mapped_column(Integer, default=443)
    xhttp_port: Mapped[int] = mapped_column(Integer, default=8443)  # 0 = disabled
    xhttp_path: Mapped[str] = mapped_column(String(64), default=lambda: "/" + secrets.token_hex(6))

    # Reality: the server impersonates this real TLS site. For whitelist regimes
    # pick a domain that is itself whitelisted (see README).
    sni: Mapped[str] = mapped_column(String(255), default="www.microsoft.com")
    private_key: Mapped[str] = mapped_column(String(64))
    public_key: Mapped[str] = mapped_column(String(64))
    short_id: Mapped[str] = mapped_column(String(16), default=lambda: secrets.token_hex(8))

    # Bridge mode: this node (e.g. inside a whitelisted Russian cloud) accepts
    # users and forwards everything non-Russian to the upstream node abroad.
    upstream_id: Mapped[int | None] = mapped_column(ForeignKey("nodes.id"))
    bridge_uuid: Mapped[str] = mapped_column(String(36), default=lambda: str(uuidlib.uuid4()))

    token: Mapped[str] = mapped_column(String(64), unique=True, index=True, default=lambda: _token(24))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sort: Mapped[int] = mapped_column(Integer, default=100)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    upstream: Mapped["Node | None"] = relationship(remote_side="Node.id", foreign_keys=[upstream_id])

    def __init__(self, **kw):
        if "private_key" not in kw:
            kw["private_key"], kw["public_key"] = generate_keypair()
        super().__init__(**kw)

    @property
    def is_bridge(self) -> bool:
        return self.upstream_id is not None

    def is_online(self, now: datetime | None = None) -> bool:
        if self.last_seen is None:
            return False
        now = now or utcnow()
        return (now - self.last_seen).total_seconds() < settings.node_offline_after_sec


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(8), default="XTR")
    days: Mapped[int] = mapped_column(Integer)
    provider_charge_id: Mapped[str] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped[User] = relationship(back_populates="payments")
