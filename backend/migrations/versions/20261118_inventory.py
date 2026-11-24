"""Create private inventory and its idempotent operation ledger."""
from alembic import op
import sqlalchemy as sa

revision = "20261118_inventory"
down_revision = "20261118_catalog"
branch_labels = None
depends_on = None

MYSQL = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}


def upgrade():
    op.create_table(
        "inventory_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("palette_color_id", sa.Integer, sa.ForeignKey("palette_colors.id"), nullable=False),
        sa.Column("stable_color_key", sa.String(36), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False, server_default="0"),
        sa.Column("unit_price", sa.Numeric(12, 4), nullable=True),
        sa.UniqueConstraint("user_id", "stable_color_key", name="uq_inventory_color"),
        sa.CheckConstraint("quantity BETWEEN 0 AND 1000000000", name="ck_inventory_quantity"),
        sa.CheckConstraint("unit_price >= 0", name="ck_inventory_price"),
        **MYSQL,
    )
    op.create_table(
        "inventory_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("request_id", sa.String(80, collation="utf8mb4_bin"), nullable=False),
        sa.Column("command", sa.JSON, nullable=False),
        sa.Column("result", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("user_id", "request_id", name="uq_inventory_request"),
        **MYSQL,
    )
    op.create_table(
        "inventory_movements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("item_id", sa.String(36), sa.ForeignKey("inventory_items.id"), nullable=False),
        sa.Column("operation_id", sa.String(36), sa.ForeignKey("inventory_requests.id"), nullable=False),
        sa.Column("project_version_id", sa.String(36), sa.ForeignKey("project_versions.id")),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("delta", sa.Integer, nullable=False),
        sa.Column("balance", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.CheckConstraint("kind IN ('stock_in','issue','return','loss')", name="ck_inventory_movement_kind"),
        sa.CheckConstraint("delta <> 0", name="ck_inventory_movement_delta"),
        **MYSQL,
    )
    op.create_index("ix_inventory_movements_time", "inventory_movements", ["item_id", "created_at", "id"])


def downgrade():
    op.drop_table("inventory_movements")
    op.drop_table("inventory_requests")
    op.drop_table("inventory_items")
