"""a coach's own screen view for one team: Classic or Updated

Revision ID: c7a3e9f1b2d4
Revises: b6e2d8f4a1c7
Create Date: 2026-10-13

Each coach chooses, per team, whether CoachBoard's planning screens show the
Classic (coachboard.io) presentation or the Updated one. It is one nullable
column on that coach's own membership row: NULL means Updated, the default,
so every existing row keeps today's screens and older code simply ignores
the column. Nothing else is rewritten; the downgrade only drops the column.
"""

from alembic import op
import sqlalchemy as sa


revision = 'c7a3e9f1b2d4'
down_revision = 'b6e2d8f4a1c7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('team_memberships', sa.Column('ui_view', sa.String(length=16), nullable=True))


def downgrade():
    with op.batch_alter_table('team_memberships') as batch_op:
        batch_op.drop_column('ui_view')
