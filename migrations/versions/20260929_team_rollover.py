"""Preserve team history and add coach memberships for season rollover."""
from alembic import op
import sqlalchemy as sa

revision = '20260929_team_rollover'
down_revision = '61099c75ca7e'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('teams', sa.Column('season_label', sa.String(80), nullable=True))
    op.add_column('teams', sa.Column('is_archived', sa.Boolean(), server_default='0', nullable=False))
    op.add_column('teams', sa.Column('rollover_key', sa.String(64), nullable=True))
    op.create_index('ix_teams_rollover_key', 'teams', ['rollover_key'], unique=True)
    op.add_column('players', sa.Column('is_active', sa.Boolean(), server_default='1', nullable=False))
    op.add_column('players', sa.Column('pitching_identity', sa.String(36), nullable=True))
    op.create_index('ix_players_pitching_identity', 'players', ['pitching_identity'])
    op.create_table('team_memberships',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), primary_key=True),
        sa.Column('team_id', sa.Integer(), sa.ForeignKey('teams.id'), primary_key=True),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('player_order', sa.JSON(), nullable=True))
    op.execute("INSERT INTO team_memberships (user_id, team_id, role, player_order) "
               "SELECT id, team_id, role, player_order FROM users")


def downgrade():
    # Restoring a pre-upgrade backup is the supported rollback. Dropping memberships
    # after rollover would strand coach accounts and disconnect pitching history.
    raise RuntimeError('Restore the pre-upgrade database backup with the old code; do not drop rollover data.')
