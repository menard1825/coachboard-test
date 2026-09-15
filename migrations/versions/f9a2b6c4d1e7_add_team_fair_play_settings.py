"""add team fair play settings

Revision ID: f9a2b6c4d1e7
Revises: d4f8b2a719ce
Create Date: 2026-08-19 21:20:00
"""

from alembic import op
import sqlalchemy as sa


revision = 'f9a2b6c4d1e7'
down_revision = 'd4f8b2a719ce'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'team_fair_play_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('team_id', sa.Integer(), nullable=False),
        sa.Column('mode', sa.String(length=20), nullable=False, server_default='off'),
        sa.Column('min_infield_innings', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('max_consecutive_bench', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('infield_positions', sa.String(length=64), nullable=False, server_default='1B,2B,3B,SS'),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('team_id', name='uq_team_fair_play_settings_team_id'),
    )
    with op.batch_alter_table('team_fair_play_settings', schema=None) as batch_op:
        batch_op.create_index('ix_team_fair_play_settings_team_id', ['team_id'], unique=True)


def downgrade():
    op.drop_table('team_fair_play_settings')
