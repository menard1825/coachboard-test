"""Add confirmed next inning prep storage

Revision ID: c7f41a2d9b10
Revises: aa343250a218
Create Date: 2026-08-14 09:30:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'c7f41a2d9b10'
down_revision = 'aa343250a218'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'game_next_inning_preps',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('inning', sa.String(), nullable=False),
        sa.Column('alignment', sa.JSON(), nullable=False),
        sa.Column('source', sa.String(), nullable=True),
        sa.Column('updated_by', sa.String(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('game_id', sa.Integer(), nullable=False),
        sa.Column('team_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['game_id'], ['games.id']),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('game_id', 'team_id', name='uq_game_next_inning_prep')
    )


def downgrade():
    op.drop_table('game_next_inning_preps')
