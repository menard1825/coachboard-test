"""Fix date format in games table

Revision ID: 8b68d5e92d2f
Revises: e80f4d3fdb2a
Create Date: 2025-09-17 20:08:14.804549

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8b68d5e92d2f'
down_revision = 'e80f4d3fdb2a'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE games SET date = substr(date, 1, 10)")


def downgrade():
    # The downgrade path is not straightforward as the original time information is lost.
    # We will leave this blank, as downgrading is not intended for this data migration.
    pass
