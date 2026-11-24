"""Verified recovery addresses and retained closures."""
from alembic import op
import sqlalchemy as sa

revision = "20261118_account_tools"
down_revision = "20261118_collab"
branch_labels = None
depends_on = None


def upgrade():
    options = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}
    op.create_table(
        "account_recovery",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("verified_at", sa.DateTime()),
        sa.Column("verify_digest", sa.String(64)),
        sa.Column("verify_until", sa.DateTime()),
        sa.Column("reset_digest", sa.String(64)),
        sa.Column("reset_until", sa.DateTime()),
        **options,
    )
    op.create_table(
        "account_closures",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        **options,
    )


def downgrade():
    op.drop_table("account_closures")
    op.drop_table("account_recovery")
