"""keep one previous Next Inning defense for Undo

Revision ID: d5a7c3e9f102
Revises: c3e8a5f1d204
Create Date: 2026-10-02

"Undo next-inning edit" restores the Next Inning defense as it was saved
before the last coach save -- its alignment, where it came from (source) and
whether a coach chose it (updated_by, 'Auto' when nobody did). Keeping that
one previous state on the row lets Undo survive a reload. revision counts
coach saves and Undos, so an Undo sent from a screen that has not seen a
newer save (another device's) is refused instead of overwriting it.
Existing rows keep NULL: nothing to undo, revision 0.
"""

from alembic import op
import sqlalchemy as sa


revision = 'd5a7c3e9f102'
down_revision = 'c3e8a5f1d204'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('game_next_inning_preps', sa.Column('previous_alignment', sa.JSON(), nullable=True))
    op.add_column('game_next_inning_preps', sa.Column('previous_source', sa.String(), nullable=True))
    op.add_column('game_next_inning_preps', sa.Column('previous_updated_by', sa.String(), nullable=True))
    op.add_column('game_next_inning_preps', sa.Column('revision', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('game_next_inning_preps') as batch_op:
        batch_op.drop_column('revision')
        batch_op.drop_column('previous_updated_by')
        batch_op.drop_column('previous_source')
        batch_op.drop_column('previous_alignment')
