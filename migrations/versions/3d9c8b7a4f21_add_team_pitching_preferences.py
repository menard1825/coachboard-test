"""add team pitching preferences

Revision ID: 3d9c8b7a4f21
Revises: f9a2b6c4d1e7
Create Date: 2026-08-20
"""

from alembic import op
import sqlalchemy as sa


revision = '3d9c8b7a4f21'
down_revision = 'f9a2b6c4d1e7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'team_pitching_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('team_id', sa.Integer(), nullable=False),
        sa.Column('competition_default_rule', sa.String(length=64), nullable=True),
        sa.Column('arm_care_rule_set', sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('team_id'),
    )
    op.create_index(
        'ix_team_pitching_settings_team_id',
        'team_pitching_settings',
        ['team_id'],
        unique=True,
    )

    # Preserve existing teams' current behavior as their optional competition
    # default, while giving every existing team Pitch Smart arm-care guidance.
    # New teams have no row until settings are saved, which means no required
    # competition default and Pitch Smart as the recommended arm-care default.
    op.execute(
        """
        INSERT INTO team_pitching_settings
            (team_id, competition_default_rule, arm_care_rule_set)
        SELECT id, pitching_rule_set, 'MLB Pitch Smart'
        FROM teams
        """
    )


def downgrade():
    op.drop_index('ix_team_pitching_settings_team_id', table_name='team_pitching_settings')
    op.drop_table('team_pitching_settings')
