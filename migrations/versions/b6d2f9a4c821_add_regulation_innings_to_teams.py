"""add regulation innings to teams

Revision ID: b6d2f9a4c821
Revises: c7f41a2d9b10
Create Date: 2026-08-14
"""

from alembic import op
import sqlalchemy as sa


revision = 'b6d2f9a4c821'
down_revision = 'c7f41a2d9b10'
branch_labels = None
depends_on = None


def upgrade():
    # NULL means Auto: CoachBoard derives 6 innings through 12U and 7 at 13U+.
    # Existing teams therefore keep their age-appropriate behavior automatically.
    with op.batch_alter_table('teams', schema=None) as batch_op:
        batch_op.add_column(sa.Column('regulation_innings', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('teams', schema=None) as batch_op:
        batch_op.drop_column('regulation_innings')
