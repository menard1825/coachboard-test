"""add coach presence tracking

Revision ID: b72c9d4e6f10
Revises: 8b1d4f6a2c90
Create Date: 2026-08-29
"""

from alembic import op
import sqlalchemy as sa


revision = 'b72c9d4e6f10'
down_revision = '8b1d4f6a2c90'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'coach_presence',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('team_id', sa.Integer(), nullable=False),
        sa.Column('browser_session_id', sa.String(length=96), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(), nullable=False),
        sa.Column('active_seconds', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('current_area', sa.String(length=80), nullable=True),
        sa.Column('current_path', sa.String(length=180), nullable=True),
        sa.Column('ip_address', sa.String(length=64), nullable=True),
        sa.Column('user_agent', sa.String(length=300), nullable=True),
        sa.Column('client_timezone', sa.String(length=80), nullable=True),
        sa.Column('client_utc_offset_minutes', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'team_id', 'browser_session_id', name='uq_coach_presence_session'),
    )
    op.create_index(op.f('ix_coach_presence_user_id'), 'coach_presence', ['user_id'], unique=False)
    op.create_index(op.f('ix_coach_presence_team_id'), 'coach_presence', ['team_id'], unique=False)
    op.create_index(op.f('ix_coach_presence_last_seen_at'), 'coach_presence', ['last_seen_at'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_coach_presence_last_seen_at'), table_name='coach_presence')
    op.drop_index(op.f('ix_coach_presence_team_id'), table_name='coach_presence')
    op.drop_index(op.f('ix_coach_presence_user_id'), table_name='coach_presence')
    op.drop_table('coach_presence')
