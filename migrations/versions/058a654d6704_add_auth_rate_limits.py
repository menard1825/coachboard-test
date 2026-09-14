"""add auth_rate_limits

Revision ID: 058a654d6704
Revises: e7c4a1b9d2f0
Create Date: 2026-09-14
"""

from alembic import op
import sqlalchemy as sa


revision = '058a654d6704'
down_revision = 'e7c4a1b9d2f0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'auth_rate_limits',
        sa.Column('key', sa.String(length=64), nullable=False),
        sa.Column('window_start', sa.BigInteger(), nullable=False),
        sa.Column('count', sa.Integer(), nullable=False, server_default='0'),
        sa.PrimaryKeyConstraint('key'),
    )
    op.create_index(
        op.f('ix_auth_rate_limits_window_start'),
        'auth_rate_limits',
        ['window_start'],
        unique=False,
    )


def downgrade():
    op.drop_index(op.f('ix_auth_rate_limits_window_start'), table_name='auth_rate_limits')
    op.drop_table('auth_rate_limits')
