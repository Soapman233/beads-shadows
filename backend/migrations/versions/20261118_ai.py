"""Durable image jobs and quota ledger."""
from alembic import op
import sqlalchemy as sa

revision = '20261118_ai'
down_revision = '20261118_workshop'
branch_labels = None
depends_on = None


def upgrade():
    options = {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4'}
    op.create_table('ai_quotas',
                    sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), primary_key=True),
                    *[sa.Column(name, sa.Integer(), nullable=False) for name in ('remaining', 'reserved', 'used')],
                    sa.CheckConstraint('remaining >= 0 AND reserved >= 0 AND used >= 0', name='ck_ai_quota'),
                    **options)
    op.create_table('ai_jobs',
                    sa.Column('id', sa.String(36), primary_key=True),
                    sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
                    sa.Column('request_id', sa.String(36), nullable=False),
                    sa.Column('input_id', sa.String(36), sa.ForeignKey('assets.id'), nullable=False),
                    sa.Column('output_id', sa.String(36), sa.ForeignKey('assets.id')),
                    sa.Column('provider', sa.String(16), nullable=False),
                    sa.Column('prompt', sa.String(1000), nullable=False),
                    sa.Column('status', sa.String(24), nullable=False),
                    sa.Column('error', sa.String(200)),
                    sa.Column('created_at', sa.DateTime(), nullable=False),
                    sa.Column('updated_at', sa.DateTime(), nullable=False),
                    sa.UniqueConstraint('user_id', 'request_id', name='uq_ai_job_request'),
                    **options)
    op.create_index('ix_ai_job_claim', 'ai_jobs', ['provider', 'status', 'created_at'])
    op.create_table('ai_quota_events',
                    sa.Column('id', sa.String(36), primary_key=True),
                    sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
                    sa.Column('job_id', sa.String(36), sa.ForeignKey('ai_jobs.id')),
                    sa.Column('request_id', sa.String(60), nullable=False),
                    sa.Column('action', sa.String(20), nullable=False),
                    sa.Column('quantity', sa.Integer(), nullable=False),
                    sa.Column('created_at', sa.DateTime(), nullable=False),
                    sa.UniqueConstraint('user_id', 'request_id', name='uq_ai_quota_request'),
                    **options)


def downgrade():
    op.drop_table('ai_quota_events')
    op.drop_table('ai_jobs')
    op.drop_table('ai_quotas')
