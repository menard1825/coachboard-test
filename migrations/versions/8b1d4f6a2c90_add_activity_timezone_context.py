"""add browser timezone context to activity log

Revision ID: 8b1d4f6a2c90
Revises: 5a7c2d9e4b11
Create Date: 2026-08-20
"""

from alembic import op
import sqlalchemy as sa


revision = '8b1d4f6a2c90'
down_revision = '5a7c2d9e4b11'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('activity_logs') as batch_op:
        batch_op.add_column(sa.Column('client_timezone', sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column('client_utc_offset_minutes', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('activity_logs') as batch_op:
        batch_op.drop_column('client_utc_offset_minutes')
        batch_op.drop_column('client_timezone')
