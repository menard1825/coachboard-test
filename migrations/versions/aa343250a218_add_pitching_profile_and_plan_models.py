"""Add Pitching Profile and Plan models

Revision ID: aa343250a218
Revises: 2141af5cf87f
Create Date: 2026-08-12 16:21:59.359383

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'aa343250a218'
down_revision = '2141af5cf87f'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('game_pitching_plans',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(), nullable=True),
        sa.Column('expected_innings', sa.String(), nullable=True),
        sa.Column('coach_note', sa.Text(), nullable=True),
        sa.Column('situational_note', sa.Text(), nullable=True),
        sa.Column('player_id', sa.Integer(), nullable=False),
        sa.Column('game_id', sa.Integer(), nullable=False),
        sa.Column('team_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['game_id'], ['games.id']),
        sa.ForeignKeyConstraint(['player_id'], ['players.id']),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id']),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('game_pitching_plans', schema=None) as batch_op:
        batch_op.create_index('idx_unique_game_pitching_plan', ['game_id', 'player_id'], unique=True)

    op.create_table('player_pitching_profiles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('traits', sa.JSON(), nullable=True),
        sa.Column('player_id', sa.Integer(), nullable=False),
        sa.Column('team_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['player_id'], ['players.id']),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('player_id')
    )


def downgrade():
    op.drop_table('player_pitching_profiles')
    with op.batch_alter_table('game_pitching_plans', schema=None) as batch_op:
        batch_op.drop_index('idx_unique_game_pitching_plan')
    op.drop_table('game_pitching_plans')
