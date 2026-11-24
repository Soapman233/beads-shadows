"""Create personal build records and moderated public snapshots."""
from alembic import op
import sqlalchemy as sa

revision = "20261118_workshop"
down_revision = "20261118_inventory"
branch_labels = None
depends_on = None

MYSQL = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}


def upgrade():
    op.create_table(
        "builds",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("project_version_id", sa.String(36), sa.ForeignKey("project_versions.id"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("request_id", sa.String(80, collation="utf8mb4_bin")),
        sa.Column("block_size", sa.Integer, nullable=False),
        sa.Column("revision", sa.Integer, nullable=False, server_default="1"),
        sa.Column("bead_count", sa.Integer, nullable=False),
        sa.Column("completed_beads", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.CheckConstraint("completed_beads BETWEEN 0 AND bead_count", name="ck_build_progress"),
        sa.UniqueConstraint("user_id", "request_id", name="uq_build_request"),
        **MYSQL,
    )
    op.create_index("ix_build_user_updated", "builds", ["user_id", "updated_at", "id"])
    op.create_table(
        "build_blocks",
        sa.Column("build_id", sa.String(36), sa.ForeignKey("builds.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("x", sa.Integer, primary_key=True),
        sa.Column("y", sa.Integer, primary_key=True),
        sa.Column("beads", sa.Integer, nullable=False),
        sa.Column("completed", sa.Boolean, nullable=False, server_default="0"),
        **MYSQL,
    )
    op.create_table(
        "publications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("author_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("project_version_id", sa.String(36), sa.ForeignKey("project_versions.id"), nullable=False),
        sa.Column("title", sa.String(80), nullable=False),
        sa.Column("category", sa.String(24), nullable=False),
        sa.Column("brand", sa.String(60)),
        sa.Column("pattern", sa.JSON, nullable=False),
        sa.Column("width", sa.Integer, nullable=False),
        sa.Column("height", sa.Integer, nullable=False),
        sa.Column("bead_count", sa.Integer, nullable=False),
        sa.Column("color_count", sa.Integer, nullable=False),
        sa.Column("allow_download", sa.Boolean, nullable=False),
        sa.Column("allow_remix", sa.Boolean, nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="pending"),
        sa.Column("decision_reason", sa.String(240)),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("published_at", sa.DateTime),
        sa.CheckConstraint("status IN ('pending','published','rejected','withdrawn','removed')", name="ck_publication_status"),
        **MYSQL,
    )
    op.create_index("ix_publication_visibility", "publications", ["status", "published_at", "id"])
    op.create_index("ix_publication_author", "publications", ["author_id", "created_at", "id"])
    op.create_table(
        "favorites",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("publication_id", sa.String(36), sa.ForeignKey("publications.id"), primary_key=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        **MYSQL,
    )
    op.create_index("ix_favorite_publication", "favorites", ["publication_id"])
    op.create_table(
        "publication_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("publication_id", sa.String(36), sa.ForeignKey("publications.id"), nullable=False),
        sa.Column("reason", sa.String(240), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="pending"),
        sa.Column("resolution", sa.String(240)),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.CheckConstraint("status IN ('pending','resolved')", name="ck_publication_report_status"),
        sa.UniqueConstraint("user_id", "publication_id", name="uq_publication_report"),
        **MYSQL,
    )
    op.create_index("ix_report_state", "publication_reports", ["status", "created_at", "id"])


def downgrade():
    op.drop_table("publication_reports")
    op.drop_table("favorites")
    op.drop_table("publications")
    op.drop_table("build_blocks")
    op.drop_table("builds")
