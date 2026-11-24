"""Store inventory, order snapshots and membership. Currency units are cents."""
from datetime import datetime

from sqlalchemy import JSON, BigInteger, CheckConstraint, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .auth import utc_now
from .db import Base


class ShopSku(Base):
    __tablename__ = "shop_skus"
    __table_args__ = (CheckConstraint("available_packs >= 0 AND price_cents >= 0 AND pieces_per_pack > 0", name="ck_sku_values"),
                      Index("ix_shop_color", "stable_color_key", "active"))

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    stable_color_key: Mapped[str] = mapped_column(String(36))
    palette_color_id: Mapped[int] = mapped_column(ForeignKey("palette_colors.id"))
    title: Mapped[str] = mapped_column(String(100))
    pieces_per_pack: Mapped[int]
    price_cents: Mapped[int]
    available_packs: Mapped[int] = mapped_column(BigInteger)
    active: Mapped[bool] = mapped_column(default=True)


class CartItem(Base):
    __tablename__ = "shop_cart"
    __table_args__ = (CheckConstraint("packs > 0 AND packs <= 1000", name="ck_cart_packs"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    sku_id: Mapped[str] = mapped_column(ForeignKey("shop_skus.id"), primary_key=True)
    packs: Mapped[int]


class MembershipPlan(Base):
    __tablename__ = "membership_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(80))
    duration_days: Mapped[int]
    price_cents: Mapped[int]
    benefits: Mapped[list] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(default=True)


class ShopOrder(Base):
    __tablename__ = "shop_orders"
    __table_args__ = (UniqueConstraint("user_id", "request_id", name="uq_shop_request"),
                      Index("ix_shop_expiring", "status", "expires_at", "id"),
                      Index("ix_shop_user_time", "user_id", "created_at", "id"))

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    request_id: Mapped[str] = mapped_column(String(80, collation="utf8mb4_bin"))
    plan_id: Mapped[str | None] = mapped_column(ForeignKey("membership_plans.id"))
    plan_snapshot: Mapped[dict | None] = mapped_column(JSON)
    total_cents: Mapped[int]
    status: Mapped[str] = mapped_column(String(24), default="awaiting_payment")
    provider: Mapped[str] = mapped_column(String(24), default="local_mock")
    expires_at: Mapped[datetime]
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now)
    tracking_reference: Mapped[str | None] = mapped_column(String(100))


class ShopOrderItem(Base):
    __tablename__ = "shop_order_items"

    order_id: Mapped[str] = mapped_column(ForeignKey("shop_orders.id"), primary_key=True)
    sku_id: Mapped[str] = mapped_column(ForeignKey("shop_skus.id"), primary_key=True)
    snapshot: Mapped[dict] = mapped_column(JSON)
    packs: Mapped[int]
    price_cents: Mapped[int]


class PaymentEvent(Base):
    __tablename__ = "shop_payment_events"
    __table_args__ = (UniqueConstraint("provider", "event_id", name="uq_payment_provider_event"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("shop_orders.id"))
    provider: Mapped[str] = mapped_column(String(24))
    event_id: Mapped[str] = mapped_column(String(80, collation="utf8mb4_bin"))
    kind: Mapped[str] = mapped_column(String(20))
    amount_cents: Mapped[int]
    currency: Mapped[str] = mapped_column(String(3))
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (Index("ix_membership_user_expiry", "user_id", "expires_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    plan_id: Mapped[str] = mapped_column(ForeignKey("membership_plans.id"))
    order_id: Mapped[str | None] = mapped_column(ForeignKey("shop_orders.id"), unique=True)
    snapshot: Mapped[dict] = mapped_column(JSON)
    starts_at: Mapped[datetime]
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
