"""Persist the session-bound lease for replacing an active collaboration grid."""
from alembic import op
import sqlalchemy as sa

revision = "20261124_structure_lease"
down_revision = "20261118_account_tools"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "room_structure_leases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("room_id", sa.String(36), sa.ForeignKey("project_rooms.id"), nullable=False),
        sa.Column("session_digest", sa.String(64, collation="utf8mb4_bin"), nullable=False),
        sa.Column("request_id", sa.String(80, collation="utf8mb4_bin"), nullable=False),
        sa.Column("base_revision", sa.Integer, nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("ended_at", sa.DateTime),
        sa.Column("receipt", sa.JSON),
        sa.UniqueConstraint("room_id", "session_digest", "request_id", name="uq_room_structure_request"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_room_structure_active", "room_structure_leases", ["room_id", "ended_at", "expires_at"])
    op.create_index("ix_project_room_archived", "project_rooms", ["project_id", "active_slot", "created_at", "id"])


def downgrade():
    op.drop_index("ix_project_room_archived", table_name="project_rooms")
    op.drop_table("room_structure_leases")
