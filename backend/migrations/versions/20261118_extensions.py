"""Store private completion records and attribution for authorized remixes."""
from alembic import op
import sqlalchemy as sa

revision = "20261118_extensions"
down_revision = "20261118_ai"
branch_labels = None
depends_on = None

MYSQL = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}


def upgrade():
    op.create_table(
        "build_completions",
        sa.Column("build_id", sa.String(36), sa.ForeignKey("builds.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("photo_id", sa.String(36), sa.ForeignKey("assets.id")),
        sa.Column("minutes", sa.Integer, nullable=False),
        sa.Column("note", sa.String(2000), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("minutes BETWEEN 0 AND 525600", name="ck_build_completion_time"),
        **MYSQL,
    )
    op.create_table(
        "project_remixes",
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), primary_key=True),
        sa.Column("publication_id", sa.String(36), sa.ForeignKey("publications.id"), nullable=False),
        sa.Column("title", sa.String(80), nullable=False),
        sa.Column("author", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        **MYSQL,
    )


def downgrade():
    op.drop_table("project_remixes")
    op.drop_table("build_completions")
