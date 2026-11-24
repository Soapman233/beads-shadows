"""Private assets, projects and immutable content revisions."""
from alembic import op
import sqlalchemy as sa

revision = '20261118_projects'
down_revision = '20261118_auth'
branch_labels = None
depends_on = None


def upgrade():
    table_options = {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4'}
    op.create_table(
        'assets',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('owner_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('size', sa.Integer(), nullable=False),
        sa.Column('width', sa.Integer(), nullable=False),
        sa.Column('height', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        **table_options,
    )
    op.create_index('ix_assets_owner', 'assets', ['owner_id'])
    op.create_table(
        'projects',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('owner_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('request_id', sa.String(80, collation='utf8mb4_bin'), nullable=False),
        sa.Column('name', sa.String(80), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime()),
        sa.UniqueConstraint('owner_id', 'request_id', name='uq_projects_import'),
        **table_options,
    )
    op.create_index('ix_projects_directory', 'projects', ['owner_id', 'deleted_at', 'updated_at', 'id'])
    op.create_table(
        'project_versions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('project_id', sa.String(36), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.Column('counts', sa.JSON(), nullable=False),
        sa.Column('bead_count', sa.Integer(), nullable=False),
        sa.Column('color_count', sa.Integer(), nullable=False),
        sa.Column('source_id', sa.String(36), sa.ForeignKey('assets.id')),
        sa.Column('mask_id', sa.String(36), sa.ForeignKey('assets.id')),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('project_id', 'revision', name='uq_project_versions_revision'),
        **table_options,
    )


def downgrade():
    op.drop_table('project_versions')
    op.drop_table('projects')
    op.drop_table('assets')
