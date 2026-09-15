"""add guest player flag

Revision ID: e7c4a1b9d2f0
Revises: b72c9d4e6f10
Create Date: 2026-09-08
"""

from alembic import op
import sqlalchemy as sa


revision = 'e7c4a1b9d2f0'
down_revision = 'b72c9d4e6f10'
branch_labels = None
depends_on = None


def upgrade():
    # SQLite supports ADD COLUMN directly. Do not use batch_alter_table here:
    # rebuilding players would require dropping a table referenced by several
    # existing foreign keys.
    op.add_column(
        'players',
        sa.Column(
            'is_guest',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade():
    op.drop_column('players', 'is_guest')
