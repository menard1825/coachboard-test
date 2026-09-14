"""add coach activity audit log

Revision ID: 5a7c2d9e4b11
Revises: 3d9c8b7a4f21
Create Date: 2026-08-20
"""

from alembic import op
import sqlalchemy as sa


revision = '5a7c2d9e4b11'
down_revision = '3d9c8b7a4f21'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'activity_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('team_id', sa.Integer(), nullable=True),
        sa.Column('username_snapshot', sa.String(length=120), nullable=False),
        sa.Column('full_name_snapshot', sa.String(length=160), nullable=True),
        sa.Column('role_snapshot', sa.String(length=64), nullable=True),
        sa.Column('action', sa.String(length=64), nullable=False),
        sa.Column('detail', sa.String(length=500), nullable=True),
        sa.Column('ip_address', sa.String(length=64), nullable=True),
        sa.Column('user_agent', sa.String(length=300), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_activity_logs_action', 'activity_logs', ['action'], unique=False)
    op.create_index('ix_activity_logs_created_at', 'activity_logs', ['created_at'], unique=False)
    op.create_index('ix_activity_logs_team_id', 'activity_logs', ['team_id'], unique=False)
    op.create_index('ix_activity_logs_user_id', 'activity_logs', ['user_id'], unique=False)


def downgrade():
    op.drop_index('ix_activity_logs_user_id', table_name='activity_logs')
    op.drop_index('ix_activity_logs_team_id', table_name='activity_logs')
    op.drop_index('ix_activity_logs_created_at', table_name='activity_logs')
    op.drop_index('ix_activity_logs_action', table_name='activity_logs')
    op.drop_table('activity_logs')
