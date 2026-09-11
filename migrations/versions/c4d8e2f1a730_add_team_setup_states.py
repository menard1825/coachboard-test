"""add guided team setup state

Revision ID: c4d8e2f1a730
Revises: 8b1d4f6a2c90
Create Date: 2026-08-22

Existing teams are intentionally NOT backfilled. A missing row means the team
predates guided setup and therefore should not receive automatic onboarding.
"""

from alembic import op
import sqlalchemy as sa


revision = 'c4d8e2f1a730'
down_revision = '8b1d4f6a2c90'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'team_setup_states',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('team_id', sa.Integer(), nullable=False),
        sa.Column('setup_type', sa.String(length=32), nullable=False),
        sa.Column('completed_steps', sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column('dismissed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('team_id', name='uq_team_setup_states_team_id'),
    )


def downgrade():
    op.drop_table('team_setup_states')
