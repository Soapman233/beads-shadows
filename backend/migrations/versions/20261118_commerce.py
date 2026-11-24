"""Create the local store, payment event ledger, and member entitlements."""
from alembic import op
import sqlalchemy as sa

revision = "20261118_commerce"
down_revision = "20261118_social"
branch_labels = None
depends_on = None

MYSQL = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}


def upgrade():
    op.create_table(
        "shop_skus",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("stable_color_key", sa.String(36), nullable=False),
        sa.Column("palette_color_id", sa.Integer, sa.ForeignKey("palette_colors.id"), nullable=False),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("pieces_per_pack", sa.Integer, nullable=False),
        sa.Column("price_cents", sa.Integer, nullable=False),
        sa.Column("available_packs", sa.BigInteger, nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default="1"),
        sa.CheckConstraint("available_packs >= 0 AND price_cents >= 0 AND pieces_per_pack > 0", name="ck_sku_values"),
        **MYSQL,
    )
    op.create_index("ix_shop_color", "shop_skus", ["stable_color_key", "active"])
    op.create_table(
        "shop_cart",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("sku_id", sa.String(36), sa.ForeignKey("shop_skus.id"), primary_key=True),
        sa.Column("packs", sa.Integer, nullable=False),
        sa.CheckConstraint("packs > 0 AND packs <= 1000", name="ck_cart_packs"),
        **MYSQL,
    )
    op.create_table(
        "membership_plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(80), nullable=False),
        sa.Column("duration_days", sa.Integer, nullable=False),
        sa.Column("price_cents", sa.Integer, nullable=False),
        sa.Column("benefits", sa.JSON, nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default="1"),
        sa.CheckConstraint("duration_days BETWEEN 1 AND 3650 AND price_cents > 0", name="ck_membership_plan_values"),
        **MYSQL,
    )
    op.create_table(
        "shop_orders",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("request_id", sa.String(80, collation="utf8mb4_bin"), nullable=False),
        sa.Column("plan_id", sa.String(36), sa.ForeignKey("membership_plans.id")),
        sa.Column("plan_snapshot", sa.JSON),
        sa.Column("total_cents", sa.Integer, nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="awaiting_payment"),
        sa.Column("provider", sa.String(24), nullable=False, server_default="local_mock"),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.Column("tracking_reference", sa.String(100)),
        sa.UniqueConstraint("user_id", "request_id", name="uq_shop_request"),
        sa.CheckConstraint("total_cents > 0", name="ck_shop_order_amount"),
        sa.CheckConstraint("status IN ('awaiting_payment','paid','failed','canceled','expired','refund_requested','refunded','shipped')", name="ck_shop_order_status"),
        **MYSQL,
    )
    op.create_index("ix_shop_expiring", "shop_orders", ["status", "expires_at", "id"])
    op.create_index("ix_shop_user_time", "shop_orders", ["user_id", "created_at", "id"])
    op.create_table(
        "shop_order_items",
        sa.Column("order_id", sa.String(36), sa.ForeignKey("shop_orders.id"), primary_key=True),
        sa.Column("sku_id", sa.String(36), sa.ForeignKey("shop_skus.id"), primary_key=True),
        sa.Column("snapshot", sa.JSON, nullable=False),
        sa.Column("packs", sa.Integer, nullable=False),
        sa.Column("price_cents", sa.Integer, nullable=False),
        sa.CheckConstraint("packs > 0 AND price_cents > 0", name="ck_shop_line_amount"),
        **MYSQL,
    )
    op.create_table(
        "shop_payment_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("order_id", sa.String(36), sa.ForeignKey("shop_orders.id"), nullable=False),
        sa.Column("provider", sa.String(24), nullable=False),
        sa.Column("event_id", sa.String(80, collation="utf8mb4_bin"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("amount_cents", sa.Integer, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("provider", "event_id", name="uq_payment_provider_event"),
        **MYSQL,
    )
    op.create_table(
        "memberships",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("plan_id", sa.String(36), sa.ForeignKey("membership_plans.id"), nullable=False),
        sa.Column("order_id", sa.String(36), sa.ForeignKey("shop_orders.id"), unique=True),
        sa.Column("snapshot", sa.JSON, nullable=False),
        sa.Column("starts_at", sa.DateTime, nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("revoked_at", sa.DateTime),
        sa.CheckConstraint("starts_at < expires_at", name="ck_membership_dates"),
        **MYSQL,
    )
    op.create_index("ix_membership_user_expiry", "memberships", ["user_id", "expires_at"])


def downgrade():
    op.drop_table("memberships")
    op.drop_table("shop_payment_events")
    op.drop_table("shop_order_items")
    op.drop_table("shop_orders")
    op.drop_table("membership_plans")
    op.drop_table("shop_cart")
    op.drop_table("shop_skus")
