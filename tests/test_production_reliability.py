"""Small production reliability fixes that must preserve existing team data."""
from io import BytesIO
from datetime import datetime, timedelta

from db import db
from models import Team, Game, Lineup, Rotation, Player, TeamMembership, CollaborationNote, PracticePlan, PracticeTask, PitchingOuting, ScoutedPlayer
from test_production_rollover import env, headers, login


PNG = b'\x89PNG\r\n\x1a\n' + b'logo-image-data'


def upload(client, filename, content):
    return client.post('/admin/upload_logo',
                       data={'logo': (BytesIO(content), filename)},
                       headers=headers(client), follow_redirects=False)


def test_logo_failure_preserves_previous_file_and_database(env, tmp_path, monkeypatch):
    app, ids = env
    logo_dir = tmp_path / 'logos'
    logo_dir.mkdir()
    app.config['UPLOAD_FOLDER'] = str(logo_dir)
    old = logo_dir / 'old.png'
    old.write_bytes(PNG)
    with app.app_context():
        Team.query.filter_by(id=ids['old']).one().logo_path = old.name
        db.session.commit()

    client = login(app)
    assert upload(client, 'logo.svg', b'<svg><script>alert(1)</script></svg>').status_code == 302
    assert upload(client, 'new.png', b'<script>not an image</script>').status_code == 302
    assert upload(client, 'huge.png', PNG + b'x' * (5 * 1024 * 1024)).status_code == 302
    assert old.read_bytes() == PNG
    with app.app_context():
        assert Team.query.filter_by(id=ids['old']).one().logo_path == old.name
    assert list(logo_dir.iterdir()) == [old]

    original_commit = db.session.commit
    def fail_commit():
        raise RuntimeError('simulated database failure')
    monkeypatch.setattr(db.session, 'commit', fail_commit)
    assert upload(client, 'new.png', PNG).status_code == 302
    monkeypatch.setattr(db.session, 'commit', original_commit)
    assert old.read_bytes() == PNG
    assert list(logo_dir.iterdir()) == [old]
    with app.app_context():
        assert Team.query.filter_by(id=ids['old']).one().logo_path == old.name


def test_logo_replacement_keeps_file_shared_by_another_team(env, tmp_path):
    app, ids = env
    logo_dir = tmp_path / 'logos'
    logo_dir.mkdir()
    app.config['UPLOAD_FOLDER'] = str(logo_dir)
    old = logo_dir / 'shared.png'
    old.write_bytes(PNG)
    with app.app_context():
        Team.query.filter_by(id=ids['old']).one().logo_path = old.name
        Team.query.filter_by(id=ids['other']).one().logo_path = old.name
        db.session.commit()

    client = login(app)
    assert upload(client, 'new.png', PNG).status_code == 302
    with app.app_context():
        replacement = Team.query.filter_by(id=ids['old']).one().logo_path
        assert replacement != old.name
        assert Team.query.filter_by(id=ids['other']).one().logo_path == old.name
    assert old.read_bytes() == PNG
    assert (logo_dir / replacement).read_bytes() == PNG


def test_position_stats_exclude_templates_and_count_each_game_once(env):
    app, ids = env
    with app.app_context():
        db.session.add(Rotation(team_id=ids['old'], title='Reusable template',
                                innings={'1': {'C': 'Departing'}}, associated_game_id=None))
        db.session.add(Rotation(team_id=ids['old'], title='Other game',
                                innings={'1': {'P': 'Graham', 'SS': 'Departing'}},
                                associated_game_id=ids['game']))
        db.session.commit()
    stats = login(app).get('/api/stats').get_json()['cumulative_position_data']
    assert stats['Graham'] == {'P': 1}
    assert 'C' not in stats['Departing']
    assert sum(stats['Departing'].values()) == 1


def test_overview_includes_games_scheduled_for_today(env):
    app, ids = env
    with app.app_context():
        today = datetime.now().date()
        old = db.session.get(Game, ids['game'])
        old.date = datetime.combine(today + timedelta(days=1), datetime.min.time())
        game = Game(team_id=ids['old'], opponent='Today',
                    date=datetime.combine(today, datetime.min.time()))
        db.session.add(game)
        db.session.commit()
        game_id = game.id
    result = login(app).get('/api/overview_data').get_json()
    assert result['next_game']['id'] == game_id


def test_renaming_player_preserves_saved_lineups_defense_notes_and_order(env):
    app, ids = env
    with app.app_context():
        db.session.add(Lineup(team_id=ids['old'], title='Template',
                              lineup_positions=['Graham'], associated_game_id=None))
        db.session.add(Rotation(team_id=ids['old'], title='Template',
                                innings={'1': {'P': 'Graham'}}, associated_game_id=None))
        db.session.add(CollaborationNote(team_id=ids['old'], note_type='player_notes',
                                         text='Work on throws', player_name='Graham'))
        db.session.commit()
    client = login(app)
    assert client.post(f"/update_player_inline/{ids['player']}",
                       data={'name': 'Graham Updated'}, headers=headers(client)).status_code == 200
    with app.app_context():
        assert db.session.get(Player, ids['player']).name == 'Graham Updated'
        assert all('Graham Updated' in l.lineup_positions
                   for l in Lineup.query.filter_by(team_id=ids['old']))
        assert all(r.innings['1']['P'] == 'Graham Updated'
                   for r in Rotation.query.filter_by(team_id=ids['old']))
        assert CollaborationNote.query.filter_by(team_id=ids['old']).one().player_name == 'Graham Updated'
        assert all('Graham Updated' in m.player_order
                   for m in TeamMembership.query.filter_by(team_id=ids['old']))
    assert 'Graham Updated' in client.get('/api/session_data').get_json()['player_order']


def test_malformed_optional_inputs_return_validation_errors(env):
    app, ids = env
    client = login(app)
    assert client.post('/save_rotation_as_template', json=[], headers=headers(client)).status_code == 400
    assert client.post('/save_rotation', json=['bad'], headers=headers(client)).status_code == 400
    assert client.post('/add_scouted_player', json=['bad'], headers=headers(client)).status_code == 400
    assert client.post('/save_player_order', json=['bad'], headers=headers(client)).status_code == 400
    assert client.post('/edit_note', data={'note_id': 'bad', 'note_text': 'Text'},
                       headers=headers(client)).status_code == 400
    assert client.post(f"/game/{ids['game']}/update_absences",
                       data={'absent_players': 'bad'}, headers=headers(client)).status_code == 400
    with app.app_context():
        plan = PracticePlan(team_id=ids['old'], date=datetime.now())
        db.session.add(plan)
        db.session.flush()
        task = PracticeTask(practice_plan_id=plan.id, text='Practice')
        db.session.add(task)
        db.session.commit()
        plan_id, task_id = plan.id, task.id
    assert client.post(f'/update_task_status/{plan_id}/{task_id}', json=[],
                       headers=headers(client)).status_code == 400
    assert client.post(f'/update_practice_attendance/{plan_id}',
                       data={'absent_players': 'bad'}, headers=headers(client)).status_code == 400
    assert client.post('/admin/settings/update', data={'outfielder_count': 'oops'},
                       headers=headers(client)).status_code == 400
    with app.app_context():
        assert db.session.get(Team, ids['old']).outfielder_count == 3


def test_invalid_scouting_move_and_pitch_count_preserve_data(env):
    app, ids = env
    with app.app_context():
        scout = ScoutedPlayer(team_id=ids['old'], name='Scout', list_type='targets')
        db.session.add(scout)
        db.session.commit()
        scout_id = scout.id
        outing_count = PitchingOuting.query.filter_by(team_id=ids['old']).count()
    client = login(app)
    assert client.post(f'/move_scouted_player/targets/lost/{scout_id}',
                       headers=headers(client)).status_code == 400
    assert client.post('/add_pitching', data={'player_id': str(ids['player']),
                       'pitches': '-10', 'innings': '2', 'pitch_date': '2026-09-29',
                       'opponent': 'Bad'}, headers=headers(client)).status_code == 302
    with app.app_context():
        assert db.session.get(ScoutedPlayer, scout_id).list_type == 'targets'
        assert PitchingOuting.query.filter_by(team_id=ids['old']).count() == outing_count


def test_committed_scout_moves_to_roster_and_keeps_coach_order(env):
    app, ids = env
    with app.app_context():
        scout = ScoutedPlayer(team_id=ids['old'], name='Incoming', list_type='committed')
        db.session.add(scout)
        db.session.commit()
        scout_id = scout.id
    client = login(app)
    assert client.post(f'/move_scouted_player_to_roster/{scout_id}',
                       headers=headers(client)).status_code == 302
    with app.app_context():
        assert db.session.get(ScoutedPlayer, scout_id) is None
        player = Player.query.filter_by(team_id=ids['old'], name='Incoming').one()
        assert player.id in db.session.get(TeamMembership, (ids['head'], ids['old'])).player_order
    assert 'Incoming' in client.get('/api/session_data').get_json()['player_order']


def test_new_roster_player_is_added_to_saved_coach_order(env):
    app, ids = env
    client = login(app)
    assert client.post('/add_player', data={'name': 'New Player'},
                       headers=headers(client)).status_code == 302
    with app.app_context():
        assert 'New Player' in db.session.get(TeamMembership, (ids['head'], ids['old'])).player_order
        assert 'New Player' in db.session.get(TeamMembership, (ids['assistant'], ids['old'])).player_order
    assert 'New Player' in client.get('/api/session_data').get_json()['player_order']


def test_settings_tabs_do_not_change_other_settings(env):
    app, ids = env
    client = login(app)
    assert client.post('/admin/settings/update',
                       data={'general_settings': '1', 'team_name': 'Prospects Fall 2026',
                             'display_coach_names': 'on', 'outfielder_count': '4'},
                       headers=headers(client)).status_code == 302
    assert client.post('/admin/settings/update',
                       data={'primary_color': '#112233', 'secondary_color': '#ddeeff'},
                       headers=headers(client)).status_code == 302
    assert client.post('/admin/settings/update',
                       data={'age_group': '13U', 'pitching_rule_set': 'MLB Pitch Smart'},
                       headers=headers(client)).status_code == 302
    with app.app_context():
        team = db.session.get(Team, ids['old'])
        assert team.display_coach_names is True
        assert team.outfielder_count == 4
        assert team.primary_color == '#112233'
        assert team.age_group == '13U'
