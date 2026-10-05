"""record which coach made the Next Inning save that Undo would take back

Revision ID: b6e2d8f4a1c7
Revises: f3c9a7d1b8e4
Create Date: 2026-10-05

Undo next-inning edit means "undo my last plan edit". updated_by is only a
display name (two coaches can share one, and it changes with the name), so
the saving coach's user id is kept as well, and only that coach may undo the
save. Existing rows keep NULL: a save recorded before this falls back to the
name it was saved under.
"""

from alembic import op
import sqlalchemy as sa


revision = 'b6e2d8f4a1c7'
down_revision = 'f3c9a7d1b8e4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('game_next_inning_preps', sa.Column('updated_by_user_id', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('game_next_inning_preps') as batch_op:
        batch_op.drop_column('updated_by_user_id')
