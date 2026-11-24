"""Create account and session tables."""
from alembic import op
import sqlalchemy as sa

revision = "20261118_auth"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(32, collation="utf8mb4_bin"), nullable=False, unique=True),
        sa.Column("nickname", sa.String(80), nullable=False),
        sa.Column("password_digest", sa.String(255), nullable=False),
        sa.Column("preferred_palette", sa.String(100), nullable=True),
        sa.Column("role", sa.String(12), nullable=False, server_default="user"),
        sa.Column("status", sa.String(12), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("role IN ('user', 'admin')", name="ck_user_role"),
        sa.CheckConstraint("status IN ('active', 'frozen')", name="ck_user_status"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_table(
        "sessions",
        sa.Column("token_digest", sa.String(64, collation="utf8mb4_bin"), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("csrf_token", sa.String(43), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_sessions_user_expires", "sessions", ["user_id", "expires_at"])


def downgrade():
    op.drop_table("sessions")
    op.drop_table("users")
