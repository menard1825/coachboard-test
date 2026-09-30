"""add game availability event fields

Revision ID: c3e8a5f1d204
Revises: b7c4d2e91a63
Create Date: 2026-09-30

A player arriving late or leaving during a live game is recorded as a
'Player Arrived' / 'Player Left' game_rotation_events row, on the same
timeline as every other live change (game_availability.py):
subject_player_id and effective_inning say whose availability changed and
from which inning. pre_start holds an On the Field change's answer to "Has
the 4th inning started?" (live_history.py). Existing rows keep NULL, which
means exactly what they meant before.
"""

from alembic import op
import sqlalchemy as sa


revision = 'c3e8a5f1d204'
down_revision = 'b7c4d2e91a63'
branch_labels = None
depends_on = None


def upgrade():
    # A plain ADD COLUMN, as in e7c4a1b9d2f0: no batch rebuild of a table that
    # holds every game's history. Alembic cannot add the foreign key to an
    # existing SQLite table, but SQLite (and PostgreSQL) accept it inline on a
    # nullable ADD COLUMN. ON DELETE SET NULL, as lineup_entries.player_id:
    # deleting a player must not be blocked by their availability history.
    op.execute(
        'ALTER TABLE game_rotation_events '
        'ADD COLUMN subject_player_id INTEGER REFERENCES players (id) ON DELETE SET NULL'
    )
    op.add_column(
        'game_rotation_events',
        sa.Column('effective_inning', sa.Integer(), nullable=True),
    )
    op.add_column(
        'game_rotation_events',
        sa.Column('pre_start', sa.Boolean(), nullable=True),
    )


def downgrade():
    with op.batch_alter_table('game_rotation_events') as batch_op:
        batch_op.drop_column('pre_start')
        batch_op.drop_column('effective_inning')
        batch_op.drop_column('subject_player_id')
