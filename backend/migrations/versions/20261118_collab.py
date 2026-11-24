"""Store collaborative permissions, rooms, and ordered edit receipts."""
from alembic import op
import sqlalchemy as sa

revision = "20261118_collab"
down_revision = "20261118_commerce"
branch_labels = None
depends_on = None

MYSQL = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}


def upgrade():
    op.create_table(
        "project_members",
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("role", sa.String(12), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.CheckConstraint("role IN ('viewer','editor')", name="ck_project_member_role"),
        **MYSQL,
    )
    op.create_table(
        "project_invitations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(12), nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("accepted_at", sa.DateTime),
        sa.Column("revoked_at", sa.DateTime),
        sa.CheckConstraint("role IN ('viewer','editor')", name="ck_project_invite_role"),
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_invite"),
        **MYSQL,
    )
    op.create_table(
        "project_rooms",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("base_version_id", sa.String(36), sa.ForeignKey("project_versions.id"), nullable=False),
        sa.Column("base_revision", sa.Integer, nullable=False),
        sa.Column("active_slot", sa.Integer),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("pattern", sa.JSON, nullable=False),
        sa.Column("latest", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.CheckConstraint("(status = 'open' AND active_slot = 1 AND active_slot IS NOT NULL) OR (status IN ('committed','closed') AND active_slot IS NULL)", name="ck_project_room_state"),
        sa.UniqueConstraint("project_id", "active_slot", name="uq_project_active_room"),
        **MYSQL,
    )
    op.create_table(
        "room_operations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("room_id", sa.String(36), sa.ForeignKey("project_rooms.id"), nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("request_id", sa.String(80, collation="utf8mb4_bin"), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("changes", sa.JSON, nullable=False),
        sa.Column("undo_of", sa.String(36), sa.ForeignKey("room_operations.id")),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("room_id", "sequence", name="uq_room_operation_sequence"),
        sa.UniqueConstraint("room_id", "actor_id", "request_id", name="uq_room_operation_request"),
        **MYSQL,
    )
    op.create_index("ix_room_actor_sequence", "room_operations", ["room_id", "actor_id", "sequence"])


def downgrade():
    op.drop_table("room_operations")
    op.drop_table("project_rooms")
    op.drop_table("project_invitations")
    op.drop_table("project_members")
