from datetime import datetime, timedelta
from pathlib import Path
import pytest
from werkzeug.security import generate_password_hash
from app import create_app
from db import db
from extensions import socketio
from models import (Team, User, Player, TeamMembership, Game, PitchingOuting, Lineup,
                    Rotation, Sign, PlayerGameAbsence, PlayerDevelopmentFocus)


@pytest.fixture()
def env(tmp_path):
    app = create_app({'TESTING': True, 'SECRET_KEY': 'test-secret',
                      'SOCKETIO_ASYNC_MODE': 'threading',
                      'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + str(tmp_path / 'test.db')})
    with app.app_context():
        db.create_all()
        old = Team(team_name='Prospects Fall 2026', registration_code='old-code')
        unrelated = Team(team_name='Unrelated', registration_code='other-code', outfielder_count=4)
        db.session.add_all([old, unrelated]); db.session.flush()
        head = User(username='head', password_hash=generate_password_hash('password'), role='Head Coach', team_id=old.id)
        assistant = User(username='assistant', password_hash=generate_password_hash('password'), role='Assistant Coach', team_id=old.id)
        outsider = User(username='outsider', password_hash=generate_password_hash('password'), role='Head Coach', team_id=unrelated.id)
        db.session.add_all([head, assistant, outsider]); db.session.flush()
        for user in [head, assistant, outsider]:
            db.session.add(TeamMembership(user_id=user.id, team_id=user.team_id, role=user.role, player_order=['Graham', 'Departing']))
        p1 = Player(name='Graham', number='12', team_id=old.id, pitcher_role='Starter', position1='1B')
        p2 = Player(name='Departing', team_id=old.id)
        p3 = Player(name='Graham', team_id=unrelated.id)
        db.session.add_all([p1,p2,p3]); db.session.flush()
        game = Game(team_id=old.id, date=datetime.now()-timedelta(days=1), opponent='Old opponent')
        foreign_game = Game(team_id=unrelated.id, date=datetime.now(), opponent='Foreign')
        db.session.add_all([game,foreign_game]);db.session.flush()
        db.session.add_all([
            PitchingOuting(team_id=old.id, player_id=p1.id, date=datetime.now()-timedelta(days=1), opponent='Old opponent', pitches=60, innings=3),
            PitchingOuting(team_id=unrelated.id, player_id=p3.id, date=datetime.now(), opponent='Other', pitches=85, innings=4),
            Lineup(team_id=old.id, title='Old lineup', lineup_positions=['Graham','Departing'], associated_game_id=game.id),
            Rotation(team_id=old.id, title='Old defense', innings={'1': {'P':'Graham','1B':'Departing'}}, associated_game_id=game.id),
            PlayerGameAbsence(team_id=old.id, player_id=p2.id, game_id=game.id),
            PlayerDevelopmentFocus(team_id=old.id, player_id=p1.id, focus='Throwing', skill_type='pitching'),
            Sign(team_id=old.id, name='Steal', indicator='Hat')])
        db.session.commit()
        ids = dict(old=old.id, other=unrelated.id, head=head.id, assistant=assistant.id, outsider=outsider.id,
                   player=p1.id, departing=p2.id, foreign_player=p3.id, game=game.id, foreign_game=foreign_game.id)
    yield app, ids
    with app.app_context(): db.session.remove(); db.drop_all()


def login(app, who='head'):
    client=app.test_client()
    response=client.post('/login',data={'username':who,'password':'password'},follow_redirects=True)
    assert response.status_code == 200
    return client


def headers(client):
    with client.session_transaction() as s:
        return {'X-Team-ID':str(s['team_id']), 'X-CSRF-Token':s['csrf_token']}


def rollover(client, ids, **extra):
    assert client.get('/teams/').status_code == 200
    with client.session_transaction() as s: nonce=s['rollover_nonce']
    data={'team_name':'Prospects Spring 2027', 'season_label':'Spring 2027','age_group':'12U',
          'players':[str(ids['player'])], 'coaches':[str(ids['assistant'])],
          'rollover_nonce':nonce, 'copy_signs':'yes'}
    data.update(extra)
    return client.post('/teams/rollover',data=data,headers=headers(client))


def test_rollover_preserves_history_and_links_pitching(env):
    app,ids=env; c=login(app)
    assert rollover(c,ids).status_code==302
    with c.session_transaction() as s: new_id=s['team_id']
    with app.app_context():
        assert new_id != ids['old']
        assert Player.query.filter_by(team_id=ids['old']).count()==2
        assert Game.query.filter_by(team_id=ids['old']).count()==1
        assert Lineup.query.filter_by(team_id=ids['old']).count()==1
        assert PlayerDevelopmentFocus.query.count()==1
        assert PlayerGameAbsence.query.count()==1
        copied=Player.query.filter_by(team_id=new_id).one()
        assert copied.name=='Graham' and copied.number=='12'
        assert copied.pitching_identity==db.session.get(Player,ids['player']).pitching_identity
        assert PitchingOuting.query.filter_by(team_id=new_id).count()==0
        assert Game.query.filter_by(team_id=new_id).count()==0
        assert Lineup.query.filter_by(team_id=new_id).count()==0
        assert TeamMembership.query.filter_by(team_id=new_id).count()==2
        assert Sign.query.filter_by(team_id=new_id).count()==1
    data=c.get('/api/pitching_data').get_json()
    assert data['pitching']==[]
    assert data['pitch_count_summary']['Graham']['weekly']==60
    assert data['pitch_count_summary']['Graham']['status']=='Resting'
    assert c.get('/api/stats').get_json()['cumulative_pitching_data']['Graham']['total_pitches_thrown']==0
    a=login(app,'assistant')
    assert a.post('/teams/switch',data={'team_id':new_id},headers=headers(a)).status_code==302
    assert a.get('/api/roster').get_json()[0]['name']=='Graham'


def test_rollover_allows_same_team_name_for_new_season(env):
    app,ids=env;c=login(app)
    assert rollover(c,ids,team_name='Prospects Fall 2026',season_label='Spring 2027').status_code==302
    with app.app_context():
        assert Team.query.filter_by(team_name='Prospects Fall 2026').count()==2
    assert c.get('/teams/').status_code==200
    assert rollover(c,ids,team_name='Prospects Fall 2026',season_label='Spring 2027').status_code==400
    with app.app_context():
        assert Team.query.filter_by(team_name='Prospects Fall 2026').count()==2


def test_switch_rejects_foreign_team_and_stale_tab_writes(env):
    app,ids=env;c=login(app); old_headers=headers(c)
    assert c.post('/teams/switch',data={'team_id':ids['other']},headers=old_headers).status_code==403
    assert rollover(c,ids).status_code==302
    assert c.post('/add_player',data={'name':'Wrong team'},headers=old_headers).status_code==409
    assert c.get('/api/roster',headers=old_headers).status_code==409
    with app.app_context(): assert Player.query.filter_by(name='Wrong team').count()==0
    assert c.post('/teams/switch',data={'team_id':ids['old']},headers=headers(c)).status_code==302
    assert len(c.get('/api/roster').get_json())==2


def test_archive_player_preserves_history_and_restores(env):
    app,ids=env;c=login(app)
    assert c.get(f"/delete_player/{ids['player']}").status_code==405
    assert c.post(f"/delete_player/{ids['player']}",headers=headers(c)).status_code==302
    assert [p['name'] for p in c.get('/api/roster').get_json()]==['Departing']
    with app.app_context():
        assert PitchingOuting.query.filter_by(player_id=ids['player']).count()==1
        assert PlayerDevelopmentFocus.query.count()==1
        assert Lineup.query.count()==1
    assert 'Graham' in c.get('/api/stats').get_json()['cumulative_pitching_data']
    assert c.post(f"/teams/players/{ids['player']}/restore",headers=headers(c)).status_code==302
    assert len(c.get('/api/roster').get_json())==2


def test_archived_team_read_only_and_restorable(env):
    app,ids=env;c=login(app)
    assert rollover(c,ids,archive_source='yes').status_code==302
    assert c.post('/teams/switch',data={'team_id':ids['old']},headers=headers(c)).status_code==302
    assert c.get('/').status_code==200
    assert c.get('/api/stats').status_code==200
    assert c.post('/add_player',data={'name':'Blocked'},headers=headers(c)).status_code==403
    assert c.post(f"/delete_game/{ids['game']}",headers=headers(c)).status_code==403
    assert c.post('/teams/archive',data={'confirmation':'Prospects Fall 2026'},headers=headers(c)).status_code==302
    assert c.post('/add_player',data={'name':'Allowed'},headers=headers(c)).status_code==302


@pytest.mark.parametrize('tamper', ['players','coaches','age_group','season_label'])
def test_rollover_validation_is_atomic(env,tamper):
    app,ids=env;c=login(app)
    value={'players':[str(ids['foreign_player'])], 'coaches':[str(ids['outsider'])], 'age_group':'invalid','season_label':''}[tamper]
    assert rollover(c,ids,**{tamper:value}).status_code==400
    with app.app_context():
        assert Team.query.count()==2
        assert db.session.get(Player,ids['player']).pitching_identity is None


def test_assistant_cannot_rollover_or_archive(env):
    app,ids=env;c=login(app,'assistant')
    assert rollover(c,ids).status_code==403
    assert c.post(f"/delete_player/{ids['player']}",headers=headers(c)).status_code==403
    assert c.post('/teams/archive',data={'confirmation':'Prospects Fall 2026'},headers=headers(c)).status_code==403


def test_csrf_and_login_required(env):
    app,ids=env;c=app.test_client()
    assert c.post('/add_player',data={'name':'Anon'}).status_code==302
    c=login(app)
    assert c.post('/add_player',data={'name':'No context'}).status_code==409
    assert c.post('/add_player',data={'name':'No token'},headers={'X-Team-ID':str(ids['old'])}).status_code==400


def test_foreign_game_and_player_references_rejected(env):
    app,ids=env;c=login(app)
    for path, payload in [('/add_lineup',{'title':'Bad','lineup_data':['Graham'],'associated_game_id':ids['foreign_game']}),
                         ('/save_rotation',{'title':'Bad','innings':{'1':{}},'associated_game_id':ids['foreign_game']})]:
        assert c.post(path,json=payload,headers=headers(c)).status_code==404
    assert c.post('/add_pitching',data={'player_id':ids['foreign_player'],'pitches':'10','innings':'1','pitch_date':'2026-09-29','opponent':'Bad'},headers=headers(c)).status_code==302
    with app.app_context(): assert PitchingOuting.query.count()==2


def test_existing_game_save_and_attendance_workflows(env):
    app,ids=env;c=login(app)
    assert c.post('/add_lineup',json={'title':'Game lineup','lineup_data':['Graham'],'associated_game_id':ids['game']},headers=headers(c)).status_code==200
    assert c.post('/save_rotation',json={'title':'Game defense','innings':{'1':{'P':'Graham'}},'associated_game_id':ids['game']},headers=headers(c)).status_code==200
    assert c.post(f"/game/{ids['game']}/update_absences",data={'absent_players':[str(ids['departing'])]},headers=headers(c)).status_code==302
    assert c.get(f"/game/{ids['game']}").status_code==200
    assert c.get('/pitching').status_code==200
    assert c.get('/admin/users').status_code==200


def test_socket_updates_are_team_scoped(env):
    app,ids=env;c=login(app);other=login(app,'outsider')
    left=socketio.test_client(app, flask_test_client=c, auth={'team_id':ids['old']})
    right=socketio.test_client(app, flask_test_client=other, auth={'team_id':ids['other']})
    assert left.is_connected() and right.is_connected()
    bad=socketio.test_client(app,flask_test_client=c,auth={'team_id':ids['other']})
    assert not bad.is_connected()
    c.post('/add_player',data={'name':'Added'},headers=headers(c))
    assert any(e['name']=='data_updated' for e in left.get_received())
    assert right.get_received()==[]
    left.disconnect();right.disconnect()


def test_coach_management_on_rolled_team(env):
    app,ids=env;c=login(app)
    assert rollover(c,ids).status_code==302
    assert c.post('/admin/edit_user/assistant',data={'full_name':'Assistant Name','role':'Game Changer'},headers=headers(c)).status_code==302
    with app.app_context():
        assert db.session.get(TeamMembership,(ids['assistant'],ids['old'])).role=='Assistant Coach'
    assert c.post('/admin/delete_user/assistant',headers=headers(c)).status_code==302
    with app.app_context():
        assert db.session.get(User,ids['assistant']) is not None
        assert TeamMembership.query.filter_by(user_id=ids['assistant']).count()==1


def test_double_submit_cannot_create_two_teams(env):
    app,ids=env;c=login(app);c.get('/teams/')
    with c.session_transaction() as s: snapshot=dict(s)
    data={'team_name':'Next','season_label':'2027','age_group':'12U','rollover_nonce':snapshot['rollover_nonce']}
    old_headers=headers(c)
    assert c.post('/teams/rollover',data=data,headers=old_headers).status_code==302
    # Replay the original signed session (e.g. two simultaneous browser requests).
    with c.session_transaction() as s: s.clear();s.update(snapshot)
    assert c.post('/teams/rollover',data=data,headers=old_headers).status_code==409
    with app.app_context(): assert Team.query.count()==3


def test_actual_upgrade_preserves_existing_production_schema(tmp_path):
    import subprocess
    from flask import Flask
    from flask_sqlalchemy import SQLAlchemy
    from flask_migrate import stamp, upgrade
    uri='sqlite:///' + str(tmp_path/'legacy.db')
    legacy_app=Flask('legacy');legacy_app.config['SQLALCHEMY_DATABASE_URI']=uri
    legacy_db=SQLAlchemy(legacy_app)
    source=subprocess.check_output(['git','show','778a670:models.py'],text=True).replace('from db import db','')
    namespace={'db':legacy_db}
    exec(compile(source,'legacy_models.py','exec'),namespace)
    with legacy_app.app_context():
        legacy_db.create_all()
        team=namespace['Team'](team_name='Legacy team', registration_code='legacy')
        legacy_db.session.add(team);legacy_db.session.flush()
        player=namespace['Player'](name='Returning',team_id=team.id)
        legacy_db.session.add(player);legacy_db.session.flush()
        user=namespace['User'](username='legacy',password_hash=generate_password_hash('password'),role='Head Coach',team_id=team.id,player_order=[player.id])
        legacy_db.session.add(user)
        legacy_db.session.add(namespace['PitchingOuting'](team_id=team.id,player_id=player.id,date=datetime.now(),pitches=45))
        legacy_db.session.commit()
        legacy_db.session.remove()
    app=create_app({'TESTING':True,'SQLALCHEMY_DATABASE_URI':uri})
    with app.app_context():
        stamp(directory='migrations',revision='61099c75ca7e')
        upgrade(directory='migrations')
        assert Team.query.one().team_name=='Legacy team'
        assert Team.query.one().is_archived is False
        assert Player.query.one().is_active is True
        assert PitchingOuting.query.one().pitches==45
        member=TeamMembership.query.one()
        assert member.role=='Head Coach' and member.player_order==[Player.query.one().id]
        assert db.session.execute(db.text('PRAGMA integrity_check')).scalar()=='ok'
        assert db.session.execute(db.text('PRAGMA foreign_key_check')).all()==[]
    c=login(app,'legacy')
    assert c.get('/api/session_data').get_json()['player_order']==['Returning']
    assert c.get('/teams/').status_code==200


def test_second_rollover_keeps_shared_workload(env):
    app,ids=env;c=login(app)
    assert rollover(c,ids).status_code==302
    with app.app_context(): copied=Player.query.filter_by(team_id=3).one();copy_id=copied.id
    next_ids=dict(ids,player=copy_id)
    assert rollover(c,next_ids,team_name='Prospects Fall 2027',season_label='Fall 2027').status_code==302
    assert c.get('/api/pitching_data').get_json()['pitch_count_summary']['Graham']['weekly']==60
    with app.app_context():
        current=Player.query.filter_by(team_id=4).one()
        db.session.add(PitchingOuting(team_id=4,player_id=current.id,date=datetime.now(),pitches=10,opponent='New game'))
        db.session.commit()
    c.post('/teams/switch',data={'team_id':ids['old']},headers=headers(c))
    assert c.get('/api/pitching_data').get_json()['pitch_count_summary']['Graham']['weekly']==70


def test_active_settings_use_selected_team(env):
    app,ids=env;c=login(app)
    assert rollover(c,ids).status_code==302
    with app.app_context():
        new_team=Team.query.filter_by(team_name='Prospects Spring 2027').one()
        new_team.outfielder_count=4;db.session.commit()
    assert c.get('/api/session_data').get_json()['session']['outfielder_count']==4
    assert c.post('/save_player_order',json={'player_order':['Graham']},headers=headers(c)).status_code==200
    assert c.post('/save_player_order',json={'player_order':['Departing']},headers=headers(c)).status_code==400


def test_new_coach_and_registration_have_memberships(env):
    app,ids=env;c=login(app)
    assert rollover(c,ids).status_code==302
    assert c.post('/admin/add_user',data={'username':'new','full_name':'New Coach','password':'password','role':'Assistant Coach'},headers=headers(c)).status_code==302
    assert login(app,'new').get('/teams/').status_code==200
    with app.app_context(): code=Team.query.filter_by(team_name='Prospects Spring 2027').one().registration_code
    newcomer=app.test_client()
    response=newcomer.post('/register',data={'username':'registered','full_name':'Registered Coach','password':'password','registration_code':code},follow_redirects=True)
    assert response.status_code==200
    with app.app_context():
        registered=User.query.filter_by(username='registered').one()
        assert TeamMembership.query.filter_by(user_id=registered.id).one().role=='Assistant Coach'


def test_removing_coach_revokes_live_updates(env):
    app,ids=env;c=login(app);a=login(app,'assistant')
    connection=socketio.test_client(app,flask_test_client=a,auth={'team_id':ids['old']})
    assert connection.is_connected()
    assert c.post('/admin/delete_user/assistant',headers=headers(c)).status_code==302
    assert not connection.is_connected()
    assert a.get('/teams/').status_code==302


def test_login_remembers_selected_team(env):
    app,ids=env;c=login(app)
    assert rollover(c,ids).status_code==302
    with c.session_transaction() as s: new_team=s['team_id']
    c.get('/logout')
    again=login(app)
    with again.session_transaction() as s: assert s['team_id']==new_team
