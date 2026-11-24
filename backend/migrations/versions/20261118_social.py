"""Create community interactions and private message tables."""
from alembic import op
import sqlalchemy as sa

revision = "20261118_social"
down_revision = "20261118_extensions"
branch_labels = None
depends_on = None

MYSQL = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}


def upgrade():
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("text", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("read_at", sa.DateTime()),
        **MYSQL,
    )
    op.create_index("ix_notice_recipient_time", "notifications", ["user_id", "created_at", "id"])
    op.create_table(
        "publication_comments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("publication_id", sa.String(36), sa.ForeignKey("publications.id"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reply_to", sa.String(36), sa.ForeignKey("publication_comments.id")),
        sa.Column("text", sa.String(1000), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime()),
        **MYSQL,
    )
    op.create_index("ix_comment_publication_time", "publication_comments", ["publication_id", "created_at", "id"])
    op.create_table(
        "direct_conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("first_user", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("second_user", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("first_user", "second_user", name="uq_conversation_users"),
        sa.CheckConstraint("first_user < second_user", name="ck_conversation_users"),
        **MYSQL,
    )
    op.create_index("ix_conversation_second", "direct_conversations", ["second_user", "updated_at"])
    op.create_table(
        "direct_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("direct_conversations.id"), nullable=False),
        sa.Column("sender_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("request_id", sa.String(80, collation="utf8mb4_bin"), nullable=False),
        sa.Column("text", sa.String(2000), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("sender_id", "request_id", name="uq_direct_message_request"),
        **MYSQL,
    )
    op.create_index("ix_direct_conversation_time", "direct_messages", ["conversation_id", "created_at", "id"])
    op.create_table(
        "user_blocks",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("blocked_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("user_id <> blocked_id", name="ck_block_other_user"),
        **MYSQL,
    )
    op.create_table(
        "social_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("reporter_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("content_id", sa.String(36), nullable=False),
        sa.Column("reason", sa.String(240), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="pending"),
        sa.Column("resolution", sa.String(240)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("reporter_id", "kind", "content_id", name="uq_social_report"),
        sa.CheckConstraint("kind IN ('comment','message') AND status IN ('pending','resolved')", name="ck_social_report_state"),
        **MYSQL,
    )
    op.create_index("ix_social_report_state", "social_reports", ["status", "created_at"])


def downgrade():
    op.drop_table("social_reports")
    op.drop_table("user_blocks")
    op.drop_table("direct_messages")
    op.drop_table("direct_conversations")
    op.drop_table("publication_comments")
    op.drop_table("notifications")
