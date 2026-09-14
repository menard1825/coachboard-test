"""normalize lineup templates and add batting-order settings

Revision ID: d4f8b2a719ce
Revises: a91c4e8b72f0
Create Date: 2026-08-19 09:30:00
"""

import json

from alembic import op
import sqlalchemy as sa


revision = 'd4f8b2a719ce'
down_revision = 'a91c4e8b72f0'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('teams', schema=None) as batch_op:
        batch_op.add_column(sa.Column('batting_order_mode', sa.String(length=20), nullable=False, server_default='bat_all'))
        batch_op.add_column(sa.Column('fixed_lineup_size', sa.Integer(), nullable=False, server_default='9'))

    with op.batch_alter_table('lineups', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()))
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()))

    op.create_table(
        'lineup_entries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('lineup_id', sa.Integer(), nullable=False),
        sa.Column('player_id', sa.Integer(), nullable=True),
        sa.Column('player_name_snapshot', sa.String(), nullable=False),
        sa.Column('batting_order', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['lineup_id'], ['lineups.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['player_id'], ['players.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('lineup_id', 'batting_order', name='uq_lineup_entry_order'),
        sa.UniqueConstraint('lineup_id', 'player_id', name='uq_lineup_entry_player'),
    )

    connection = op.get_bind()
    lineups = connection.execute(sa.text(
        'SELECT id, team_id, lineup_positions FROM lineups ORDER BY id'
    )).mappings()
    for lineup in lineups:
        raw_names = lineup['lineup_positions']
        if isinstance(raw_names, str):
            try:
                raw_names = json.loads(raw_names)
            except (TypeError, ValueError):
                raw_names = []
        if not isinstance(raw_names, list):
            continue

        roster = connection.execute(sa.text(
            'SELECT id, name FROM players WHERE team_id = :team_id'
        ), {'team_id': lineup['team_id']}).mappings().all()
        by_name = {}
        duplicate_names = set()
        for player in roster:
            if player['name'] in by_name:
                duplicate_names.add(player['name'])
            by_name[player['name']] = player['id']

        used_player_ids = set()
        batting_order = 0
        for raw_name in raw_names:
            name = str(raw_name).strip()
            if not name:
                continue
            batting_order += 1
            player_id = None if name in duplicate_names else by_name.get(name)
            if player_id in used_player_ids:
                player_id = None
            if player_id is not None:
                used_player_ids.add(player_id)
            connection.execute(sa.text(
                'INSERT INTO lineup_entries '
                '(lineup_id, player_id, player_name_snapshot, batting_order) '
                'VALUES (:lineup_id, :player_id, :name, :batting_order)'
            ), {
                'lineup_id': lineup['id'],
                'player_id': player_id,
                'name': name,
                'batting_order': batting_order,
            })


def downgrade():
    op.drop_table('lineup_entries')
    # These columns have no dependent constraints. Direct DROP COLUMN avoids
    # SQLite's batch-table recreation, which cannot replace a referenced teams
    # table while foreign-key enforcement is enabled.
    op.drop_column('lineups', 'updated_at')
    op.drop_column('lineups', 'created_at')
    op.drop_column('lineups', 'is_default')
    op.drop_column('teams', 'fixed_lineup_size')
    op.drop_column('teams', 'batting_order_mode')
