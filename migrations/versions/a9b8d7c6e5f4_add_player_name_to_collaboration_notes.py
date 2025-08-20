"""Add player_name to collaboration_notes

Revision ID: a9b8d7c6e5f4
Revises: 1234567890ab
Create Date: 2025-08-20 23:43:27.277110

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a9b8d7c6e5f4'
down_revision = '1234567890ab'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('collaboration_notes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('player_name', sa.String(length=100), nullable=True))


def downgrade():
    with op.batch_alter_table('collaboration_notes', schema=None) as batch_op:
        batch_op.drop_column('player_name')
