"""add hot query indexes

Revision ID: b7c4d2e91a63
Revises: 058a654d6704
Create Date: 2026-09-16

Adds indexes for repeatedly observed hot query shapes in the modern
CoachBoard application.

Notes:
- Existing GamePitchingPlan and PlayerPitchTarget partial unique indexes
  are intentionally preserved.
- games(team_id, date, start_time, id) substantially improves team/date
  game history queries, although queries ordered by date,id without
  start_time may still require a small right-side temp sort.
"""

from alembic import op


revision = 'b7c4d2e91a63'
down_revision = '058a654d6704'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        'idx_team_memberships_user_team',
        'team_memberships',
        ['user_id', 'team_id'],
        unique=False,
    )
    op.create_index(
        'idx_team_memberships_team',
        'team_memberships',
        ['team_id'],
        unique=False,
    )

    op.create_index(
        'idx_players_team_name',
        'players',
        ['team_id', 'name'],
        unique=False,
    )

    op.create_index(
        'idx_games_team_live_id',
        'games',
        ['team_id', 'is_live', 'id'],
        unique=False,
    )
    op.create_index(
        'idx_games_team_date_start_id',
        'games',
        ['team_id', 'date', 'start_time', 'id'],
        unique=False,
    )

    op.create_index(
        'idx_lineups_team_game',
        'lineups',
        ['team_id', 'associated_game_id'],
        unique=False,
    )

    op.create_index(
        'idx_rotations_team_game',
        'rotations',
        ['team_id', 'associated_game_id'],
        unique=False,
    )

    op.create_index(
        'idx_game_rotation_events_team_game_sequence_id',
        'game_rotation_events',
        ['team_id', 'game_id', 'sequence', 'id'],
        unique=False,
    )
    op.create_index(
        'idx_game_rotation_events_game_sequence_id',
        'game_rotation_events',
        ['game_id', 'sequence', 'id'],
        unique=False,
    )

    op.create_index(
        'idx_player_game_absences_team_game_player',
        'player_game_absences',
        ['team_id', 'game_id', 'player_id'],
        unique=False,
    )

    op.create_index(
        'idx_pitching_outings_game',
        'pitching_outings',
        ['game_id'],
        unique=False,
    )
    op.create_index(
        'idx_pitching_outings_team_player_date',
        'pitching_outings',
        ['team_id', 'player_id', 'date'],
        unique=False,
    )

    op.create_index(
        'idx_player_pitch_targets_team',
        'player_pitch_targets',
        ['team_id'],
        unique=False,
    )


def downgrade():
    op.drop_index(
        'idx_player_pitch_targets_team',
        table_name='player_pitch_targets',
    )

    op.drop_index(
        'idx_pitching_outings_team_player_date',
        table_name='pitching_outings',
    )
    op.drop_index(
        'idx_pitching_outings_game',
        table_name='pitching_outings',
    )

    op.drop_index(
        'idx_player_game_absences_team_game_player',
        table_name='player_game_absences',
    )

    op.drop_index(
        'idx_game_rotation_events_game_sequence_id',
        table_name='game_rotation_events',
    )
    op.drop_index(
        'idx_game_rotation_events_team_game_sequence_id',
        table_name='game_rotation_events',
    )

    op.drop_index(
        'idx_rotations_team_game',
        table_name='rotations',
    )

    op.drop_index(
        'idx_lineups_team_game',
        table_name='lineups',
    )

    op.drop_index(
        'idx_games_team_date_start_id',
        table_name='games',
    )
    op.drop_index(
        'idx_games_team_live_id',
        table_name='games',
    )

    op.drop_index(
        'idx_players_team_name',
        table_name='players',
    )

    op.drop_index(
        'idx_team_memberships_team',
        table_name='team_memberships',
    )
    op.drop_index(
        'idx_team_memberships_user_team',
        table_name='team_memberships',
    )
