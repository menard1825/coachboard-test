"""record whether a saved Next Inning defense's pitcher was chosen

Revision ID: f3c9a7d1b8e4
Revises: e8b2f4a6c913
Create Date: 2026-10-02

A coach's Next Inning save used to fix every position, the pitcher
included, even when the coach only moved fielders. pitcher_chosen records
whether the save changed P on the board; a defense whose pitcher was not
chosen follows a live pitching change (carry_planned_pitcher), one whose
pitcher was chosen keeps it. previous_pitcher_chosen goes with the one-step
Undo state. Existing rows keep NULL: not chosen.
"""

from alembic import op
import sqlalchemy as sa


revision = 'f3c9a7d1b8e4'
down_revision = 'e8b2f4a6c913'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('game_next_inning_preps', sa.Column('pitcher_chosen', sa.Boolean(), nullable=True))
    op.add_column('game_next_inning_preps', sa.Column('previous_pitcher_chosen', sa.Boolean(), nullable=True))


def downgrade():
    with op.batch_alter_table('game_next_inning_preps') as batch_op:
        batch_op.drop_column('previous_pitcher_chosen')
        batch_op.drop_column('pitcher_chosen')
