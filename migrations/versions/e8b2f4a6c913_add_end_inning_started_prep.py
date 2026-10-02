"""keep the Next Inning defense an End Inning started with

Revision ID: e8b2f4a6c913
Revises: d5a7c3e9f102
Create Date: 2026-10-02

End Inning starts the next inning with the saved Next Inning defense and
clears it. Undoing that start used to seed a new automatic defense, losing
the coach's edits for the inning. The End Inning event now keeps the saved
defense's metadata (source, who chose it, revision, its own Undo state) in
started_prep so Undo can restore it exactly; the alignment is the event's
after_alignment. Existing rows keep NULL and behave as before.
"""

from alembic import op
import sqlalchemy as sa


revision = 'e8b2f4a6c913'
down_revision = 'd5a7c3e9f102'
branch_labels = None
depends_on = None


def upgrade():
    # A plain ADD COLUMN, as in c3e8a5f1d204: no batch rebuild of the table
    # that holds every game's history.
    op.add_column('game_rotation_events', sa.Column('started_prep', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('game_rotation_events') as batch_op:
        batch_op.drop_column('started_prep')
