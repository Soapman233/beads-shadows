"""Create versioned colour catalog and administrative audit tables."""
from alembic import op
import sqlalchemy as sa

revision = "20261118_catalog"
down_revision = "20261118_projects"
branch_labels = None
depends_on = None

MYSQL = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}


def upgrade():
    op.create_table(
        "palettes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("brand", sa.String(60), nullable=False),
        sa.Column("series", sa.String(60), nullable=False),
        sa.Column("size_mm", sa.Numeric(5, 2), nullable=False),
        sa.UniqueConstraint("brand", "series", "size_mm", name="uq_palette_identity"),
        **MYSQL,
    )
    op.create_table(
        "palette_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("palette_id", sa.String(36), sa.ForeignKey("palettes.id"), nullable=False),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("source", sa.String(800), nullable=False),
        sa.Column("license_status", sa.String(30), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("palette_id", "label", name="uq_palette_label"),
        sa.CheckConstraint("status IN ('draft','published','retired')", name="ck_palette_version_status"),
        **MYSQL,
    )
    op.create_index("ix_palette_version_state", "palette_versions", ["palette_id", "status"])
    op.create_table(
        "palette_colors",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("version_id", sa.String(36), sa.ForeignKey("palette_versions.id"), nullable=False),
        sa.Column("code", sa.String(32, collation="utf8mb4_bin"), nullable=False),
        sa.Column("hex", sa.String(7), nullable=False),
        sa.Column("material", sa.String(60), nullable=False),
        sa.Column("stable_color_key", sa.String(36), nullable=False),
        sa.UniqueConstraint("version_id", "code", name="uq_palette_code"),
        sa.UniqueConstraint("version_id", "stable_color_key", name="uq_palette_stable_key"),
        **MYSQL,
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(45), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("summary", sa.String(240), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        **MYSQL,
    )
    op.create_index("ix_audit_created", "audit_logs", ["created_at", "id"])


def downgrade():
    op.drop_table("audit_logs")
    op.drop_table("palette_colors")
    op.drop_table("palette_versions")
    op.drop_table("palettes")
