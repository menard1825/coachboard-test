"""Refactor PitchingOuting to use player_id

Revision ID: 1234567890ab
Revises: 9def09453471
Create Date: 2025-08-11 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1234567890ab'
down_revision = '9def09453471'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('pitching_outings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('player_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_pitching_outings_player_id', 'players', ['player_id'], ['id'])

    # Data migration
    bind = op.get_bind()
    Session = sa.orm.sessionmaker(bind=bind)
    session = Session()

    players_table = sa.Table('players', sa.MetaData(), sa.Column('id', sa.Integer), sa.Column('name', sa.String))
    pitching_outings_table = sa.Table('pitching_outings', sa.MetaData(), sa.Column('id', sa.Integer), sa.Column('pitcher', sa.String), sa.Column('player_id', sa.Integer))

    players = session.execute(sa.select(players_table)).fetchall()
    player_map = {p.name.lower(): p.id for p in players}

    outings = session.execute(sa.select(pitching_outings_table)).fetchall()
    for outing in outings:
        player_id = player_map.get(str(outing.pitcher).lower()) if outing.pitcher else None
        if player_id:
            session.execute(
                pitching_outings_table.update().where(pitching_outings_table.c.id == outing.id).values(player_id=player_id)
            )
    session.commit()

    with op.batch_alter_table('pitching_outings', schema=None) as batch_op:
        batch_op.alter_column('player_id', existing_type=sa.Integer(), nullable=False)
        batch_op.drop_column('pitcher')


def downgrade():
    with op.batch_alter_table('pitching_outings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('pitcher', sa.String(), nullable=True))

    # Data migration back to names (best effort)
    bind = op.get_bind()
    Session = sa.orm.sessionmaker(bind=bind)
    session = Session()

    players_table = sa.Table('players', sa.MetaData(), sa.Column('id', sa.Integer), sa.Column('name', sa.String))
    pitching_outings_table = sa.Table('pitching_outings', sa.MetaData(), sa.Column('id', sa.Integer), sa.Column('pitcher', sa.String), sa.Column('player_id', sa.Integer))

    players = session.execute(sa.select(players_table)).fetchall()
    player_map = {p.id: p.name for p in players}

    outings = session.execute(sa.select(pitching_outings_table)).fetchall()
    for outing in outings:
        player_name = player_map.get(outing.player_id)
        if player_name:
            session.execute(
                pitching_outings_table.update().where(pitching_outings_table.c.id == outing.id).values(pitcher=player_name)
            )
    session.commit()

    with op.batch_alter_table('pitching_outings', schema=None) as batch_op:
        batch_op.alter_column('pitcher', existing_type=sa.String(), nullable=False)
        batch_op.drop_constraint('fk_pitching_outings_player_id', type_='foreignkey')
        batch_op.drop_column('player_id')
