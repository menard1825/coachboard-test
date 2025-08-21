"""Merge stray debug migration head

Revision ID: 7aab96ec69ee
Revises: a9b8d7c6e5f4, 1d5da43b82b4
Create Date: 2025-08-20 23:51:00.849025

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7aab96ec69ee'
down_revision = ('a9b8d7c6e5f4', '1d5da43b82b4')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
