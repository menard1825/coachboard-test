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
    # Add the player_id column as nullable first
    op.add_column('pitching_outings', sa.Column('player_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_pitching_outings_player_id', 'pitching_outings', 'players', ['player_id'], ['id'])

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
        player_id = player_map.get(outing.pitcher.lower())
        if player_id:
            session.execute(
                pitching_outings_table.update().where(pitching_outings_table.c.id == outing.id).values(player_id=player_id)
            )

    session.commit()

    # Now make player_id non-nullable and drop the old pitcher column
    op.alter_column('pitching_outings', 'player_id', existing_type=sa.Integer(), nullable=False)
    op.drop_column('pitching_outings', 'pitcher')


def downgrade():
    op.add_column('pitching_outings', sa.Column('pitcher', sa.String(), nullable=True))

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

    op.alter_column('pitching_outings', 'pitcher', existing_type=sa.String(), nullable=False)
    op.drop_constraint('fk_pitching_outings_player_id', 'pitching_outings', type_='foreignkey')
    op.drop_column('pitching_outings', 'player_id')
