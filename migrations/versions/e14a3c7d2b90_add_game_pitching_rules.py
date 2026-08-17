"""add game pitching rule overrides

Revision ID: e14a3c7d2b90
Revises: b6d2f9a4c821
Create Date: 2026-08-17
"""

from alembic import op
import sqlalchemy as sa


revision = 'e14a3c7d2b90'
down_revision = 'b6d2f9a4c821'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'game_pitching_rules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('rule_set', sa.String(), nullable=False),
        sa.Column('game_id', sa.Integer(), nullable=False),
        sa.Column('team_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['game_id'], ['games.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('game_id'),
    )


def downgrade():
    op.drop_table('game_pitching_rules')
