"""add game clock state

Revision ID: a91c4e8b72f0
Revises: f4c1a8d92e31
Create Date: 2026-08-18 10:35:00
"""

from alembic import op
import sqlalchemy as sa


revision = 'a91c4e8b72f0'
down_revision = 'f4c1a8d92e31'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'game_clock_states',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('game_id', sa.Integer(), nullable=False),
        sa.Column('team_id', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('ended_at', sa.DateTime(), nullable=True),
        sa.Column('time_limit_minutes', sa.Integer(), nullable=True),
        sa.Column('end_reason', sa.String(length=32), nullable=True),
        sa.Column('last_played_inning', sa.String(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['game_id'], ['games.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('game_id', 'team_id', name='uq_game_clock_state_game_team'),
    )


def downgrade():
    op.drop_table('game_clock_states')
