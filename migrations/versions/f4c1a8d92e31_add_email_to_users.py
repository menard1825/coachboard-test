"""add email to users

Revision ID: f4c1a8d92e31
Revises: e14a3c7d2b90
Create Date: 2026-08-17 16:40:00
"""

from alembic import op
import sqlalchemy as sa


revision = 'f4c1a8d92e31'
down_revision = 'e14a3c7d2b90'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('email', sa.String(length=255), nullable=True))
        batch_op.create_unique_constraint('uq_users_email', ['email'])


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_constraint('uq_users_email', type_='unique')
        batch_op.drop_column('email')
