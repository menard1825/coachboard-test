from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from werkzeug.datastructures import MultiDict
from werkzeug.security import generate_password_hash


def _build_app(monkeypatch):
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')

    from app import create_app
    from db import db
    from models import Team, TeamMembership, User

    app = create_app()
    app.config.update(TESTING=True)

    with app.app_context():
        db.create_all()
        team = Team(
            id=1,
            team_name='Test Team',
            registration_code='test-code',
            age_group='12U',
            pitching_rule_set='MLB Pitch Smart',
            outfielder_count=3,
            timezone='America/Indiana/Indianapolis',
        )
        user = User(
            id=1,
            username='coach',
            full_name='Test Coach',
            password_hash=generate_password_hash('password123'),
        )
        db.session.add_all([team, user])
        db.session.flush()
        db.session.add(TeamMembership(
            user_id=user.id,
            team_id=team.id,
            role='Head Coach',
            player_order=[],
        ))
        db.session.commit()

    return app


def _login(client):
    with client.session_transaction() as session:
        session['logged_in'] = True
        session['username'] = 'coach'
        session['team_id'] = 1
        session['role'] = 'Head Coach'


def test_production_requires_explicit_secret(monkeypatch):
    monkeypatch.delenv('SECRET_KEY', raising=False)
    monkeypatch.setenv('COACHBOARD_ENV', 'production')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')

    from app import create_app

    with pytest.raises(RuntimeError, match='SECRET_KEY'):
        create_app()


def test_legacy_live_game_mutation_is_retired(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    response = client.post('/toggle_live_game', json={'game_id': 1, 'is_live': True})

    assert response.status_code == 410
    assert 'older CoachBoard client' in response.get_json()['message']


def test_head_coach_cannot_forge_super_admin_assignment(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    response = client.post('/admin/add_user', data={
        'username': 'existing-user',
        'password': 'temporary-password',
        'role': 'Super Admin',
    })

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/admin/users')


def test_cross_site_destructive_get_is_blocked(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    response = client.get('/delete_player/1', headers={'Sec-Fetch-Site': 'cross-site'})

    assert response.status_code == 403
    assert 'Cross-site destructive request blocked' in response.get_json()['message']


def test_stale_membership_session_is_rejected(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    from db import db
    from models import TeamMembership

    with app.app_context():
        db.session.query(TeamMembership).delete()
        db.session.commit()

    response = client.get('/api/roster')

    assert response.status_code == 401
    assert 'team access is no longer active' in response.get_json()['message']


def test_read_only_api_does_not_reissue_a_stale_permanent_session(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)
    with client.session_transaction() as session:
        session.permanent = True

    response = client.get('/api/roster')

    assert response.status_code == 200
    assert 'Set-Cookie' not in response.headers


def test_incomplete_pitch_history_never_becomes_zero_total():
    from blueprints.stats_dashboard import _apply_pitch_completeness

    dashboard = {
        'summary': {'team_pitching_pitches': 42},
        'pitching_usage': [{
            'player_id': 7,
            'total_pitches': 42,
            'pitches_per_appearance': 42.0,
            'pitch_share_pct': 100,
        }],
    }
    outings = [
        SimpleNamespace(player_id=7, pitches=42),
        SimpleNamespace(player_id=7, pitches=None),
    ]

    _apply_pitch_completeness(dashboard, outings)

    row = dashboard['pitching_usage'][0]
    assert row['pitch_history_complete'] is False
    assert row['known_pitches'] == 42
    assert row['total_pitches'] is None
    assert row['pitches_per_appearance'] is None
    assert dashboard['summary']['team_pitching_pitches'] is None
    assert dashboard['summary']['known_team_pitching_pitches'] == 42


def test_gamechanger_innings_parser_uses_baseball_out_notation():
    from blueprints.live_game_pitching_api import _parse_innings

    assert _parse_innings({'innings_whole': 2, 'innings_outs': 0}) == 2.0
    assert _parse_innings({'innings_whole': 2, 'innings_outs': 1}) == 2.1
    assert _parse_innings({'innings_whole': 2, 'innings_outs': 2}) == 2.2
    assert _parse_innings({'innings_whole': '', 'innings_outs': 1}) is None


def test_game_clock_time_limit_persists(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    from db import db
    from models import Game

    with app.app_context():
        db.session.add(Game(
            id=10,
            date=datetime(2026, 8, 18),
            opponent='Clock Test',
            team_id=1,
        ))
        db.session.commit()

    response = client.post('/api/live-game/10/clock', json={'time_limit_minutes': 100})

    assert response.status_code == 200
    payload = response.get_json()['clock']
    assert payload['time_limit_minutes'] == 100
    assert payload['is_live'] is False


def test_lineups_use_stable_player_ids_and_follow_safe_renames(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    from db import db
    from models import Player, Team

    with app.app_context():
        db.session.add_all([
            Player(id=1, name='Alpha', team_id=1),
            Player(id=2, name='Bravo', team_id=1),
            Team(
                id=2,
                team_name='Other Team',
                registration_code='other-code',
                age_group='12U',
                pitching_rule_set='MLB Pitch Smart',
                outfielder_count=3,
                timezone='America/Indiana/Indianapolis',
            ),
            Player(id=20, name='Other Player', team_id=2),
        ])
        db.session.commit()

    created = client.post('/add_lineup', json={
        'title': 'ID Order',
        'lineup_player_ids': [2, 1],
        'is_default': True,
    })
    assert created.status_code == 200
    payload = created.get_json()['lineup']
    assert payload['lineup_player_ids'] == [2, 1]
    assert payload['is_default'] is True

    renamed = client.post('/update_player_inline/2', data={'name': 'Bravo Renamed'})
    assert renamed.status_code == 200
    saved = client.get('/api/lineups').get_json()[0]
    assert saved['lineup_player_ids'] == [2, 1]
    assert saved['lineup_positions'] == ['Bravo Renamed', 'Alpha']
    assert saved['lineup_entries'][0]['player_name_snapshot'] == 'Bravo Renamed'

    deleted = client.get('/delete_player/2')
    assert deleted.status_code == 302
    archived = client.get('/api/lineups').get_json()[0]
    assert archived['lineup_positions'] == ['Bravo Renamed', 'Alpha']
    assert archived['lineup_entries'][0]['player_id'] is None
    assert archived['lineup_entries'][0]['available'] is False

    rejected = client.post('/add_lineup', json={
        'title': 'Cross Team',
        'lineup_player_ids': [20],
    })
    assert rejected.status_code == 400
    assert 'not on this team' in rejected.get_json()['message']


def test_lineup_readiness_respects_bat_all_and_fixed_modes(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    from db import db
    from models import Game, Player, Team

    with app.app_context():
        db.session.add_all([
            Player(id=1, name='Alpha', team_id=1),
            Player(id=2, name='Bravo', team_id=1),
            Player(id=3, name='Charlie', team_id=1),
            Game(id=30, date=datetime(2026, 8, 19), opponent='Readiness Test', team_id=1),
        ])
        db.session.commit()

    created = client.post('/add_lineup', json={
        'title': 'Game Order',
        'lineup_player_ids': [1, 2],
        'associated_game_id': 30,
    }).get_json()
    lineup_id = created['new_id']
    readiness = client.get('/api/game-day/30/readiness').get_json()['readiness']
    assert readiness['lineup_mode'] == 'bat_all'
    assert readiness['lineup_expected_count'] == 3
    assert readiness['lineup_ready'] is False

    client.post(f'/edit_lineup/{lineup_id}', json={
        'title': 'Game Order',
        'lineup_player_ids': [1, 2, 3],
        'associated_game_id': 30,
    })
    readiness = client.get('/api/game-day/30/readiness').get_json()['readiness']
    assert readiness['lineup_ready'] is True

    with app.app_context():
        team = db.session.get(Team, 1)
        team.batting_order_mode = 'fixed'
        team.fixed_lineup_size = 2
        db.session.commit()

    client.post(f'/edit_lineup/{lineup_id}', json={
        'title': 'Game Order',
        'lineup_player_ids': [3, 1],
        'associated_game_id': 30,
    })
    readiness = client.get('/api/game-day/30/readiness').get_json()['readiness']
    assert readiness['lineup_mode'] == 'fixed'
    assert readiness['lineup_expected_count'] == 2
    assert readiness['lineup_ready'] is True


def test_time_limit_can_exclude_loaded_but_unplayed_next_inning(monkeypatch):
    app = _build_app(monkeypatch)

    from blueprints.live_game_clock import _adjust_unplayed_current_inning
    from db import db
    from models import Game, GameRotationEvent

    with app.app_context():
        game = Game(
            id=11,
            date=datetime(2026, 8, 18),
            opponent='Time Limit Test',
            team_id=1,
            is_live=False,
            live_current_inning='5',
        )
        transition = GameRotationEvent(
            team_id=1,
            game_id=11,
            inning='5',
            sequence=1,
            event_type='End Inning',
            before_alignment={'P': 'Pitcher Four'},
            after_alignment={'P': 'Pitcher Five'},
            reverted=False,
        )
        end_event = GameRotationEvent(
            team_id=1,
            game_id=11,
            inning='5',
            sequence=2,
            event_type='End Game',
            before_alignment={'P': 'Pitcher Five'},
            after_alignment={'P': 'Pitcher Five'},
            reverted=False,
        )
        db.session.add_all([game, transition, end_event])
        db.session.commit()

        last_played = _adjust_unplayed_current_inning(game, 1)
        db.session.commit()

        assert last_played == '4'
        assert game.live_current_inning == '4'
        assert transition.reverted is True
        assert end_event.inning == '4'
        assert end_event.after_alignment == {'P': 'Pitcher Four'}


def test_completed_game_opens_actual_report_by_default(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    from db import db
    from models import Game, GameRotationEvent

    with app.app_context():
        game = Game(
            id=12,
            date=datetime(2026, 8, 18),
            opponent='Completed Game',
            team_id=1,
            is_live=False,
            live_current_inning='3',
        )
        db.session.add(game)
        db.session.flush()
        db.session.add(GameRotationEvent(
            team_id=1,
            game_id=12,
            inning='3',
            sequence=1,
            event_type='End Game',
            before_alignment={'P': 'Pitcher'},
            after_alignment={'P': 'Pitcher'},
            reverted=False,
        ))
        db.session.commit()

    response = client.get('/game/12', follow_redirects=False)

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/game-day/12/report')


def test_game_management_renders_dugout_friendly_pitching_controls(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    from db import db
    from models import Game, Player

    with app.app_context():
        db.session.add_all([
            Game(
                id=13,
                date=datetime(2026, 8, 18),
                opponent='Dugout UX Test',
                team_id=1,
            ),
            Player(
                id=2,
                name='Primary First Baseman',
                position1='1B',
                team_id=1,
            ),
        ])
        db.session.commit()

    response = client.get('/game/13')

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'data-pitch-step="5"' in html
    assert 'data-pitch-target="innings_whole"' in html
    assert 'gameday_pitching_steppers.js' in html
    assert '<span class="pitch-header-limit">Max 85</span>' in html
    assert '/ 85 game pitches' not in html
    assert 'title="Games + practice + lessons"' in html
    assert 'href="/game-day"' in html
    assert '/#games' not in html


def test_game_availability_updates_safely_and_returns_to_open_panel(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    from db import db
    from models import Game, Player, PlayerGameAbsence

    with app.app_context():
        db.session.add_all([
            Game(
                id=15,
                date=datetime(2026, 8, 19),
                opponent='Availability Test',
                team_id=1,
            ),
            Player(id=21, name='Available Player', team_id=1),
        ])
        db.session.commit()

    saved = client.post(
        '/game/15/update_absences',
        data=MultiDict([
            ('absent_players', '21'),
            ('absent_players', '21'),
        ]),
        follow_redirects=False,
    )
    assert saved.status_code == 302
    assert saved.headers['Location'].endswith('/game/15#availabilityCollapse')

    with app.app_context():
        rows = db.session.query(PlayerGameAbsence).filter_by(game_id=15, team_id=1).all()
        assert [row.player_id for row in rows] == [21]

    rejected = client.post(
        '/game/15/update_absences',
        data={'absent_players': 'not-a-player'},
        follow_redirects=False,
    )
    assert rejected.status_code == 302
    assert rejected.headers['Location'].endswith('/game/15#availabilityCollapse')
    with app.app_context():
        assert db.session.query(PlayerGameAbsence).filter_by(game_id=15, team_id=1).count() == 1

    page = client.get('/game/15')
    html = page.get_data(as_text=True)
    assert 'id="availabilityToggleBtn"' in html
    assert 'aria-controls="availabilityCollapse"' in html
    assert 'id="saveGameAvailabilityBtn"' in html

    blank_opponent = client.post('/edit_game/15', data={'game_opponent': '   '})
    assert blank_opponent.status_code == 302
    with app.app_context():
        assert db.session.get(Game, 15).opponent == 'Availability Test'

    edited = client.post('/edit_game/15', data={
        'game_date': '2026-08-20',
        'game_start_time': ' 18:30 ',
        'game_opponent': ' Updated Opponent ',
        'game_location': ' Field 7 ',
        'game_notes': ' Bring water ',
    })
    assert edited.status_code == 302
    with app.app_context():
        game = db.session.get(Game, 15)
        assert game.opponent == 'Updated Opponent'
        assert game.start_time == '18:30'
        assert game.location == 'Field 7'
        assert game.game_notes == 'Bring water'


def test_starting_defense_template_allows_open_pitcher_and_reaches_game_day(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    from db import db
    from models import Game, Player, Rotation

    alignment = {
        'C': 'Starting Catcher',
        '1B': 'Starting First',
        '2B': 'Starting Second',
        '3B': 'Starting Third',
        'SS': 'Starting Shortstop',
        'LF': 'Starting Left',
        'CF': 'Starting Center',
        'RF': 'Starting Right',
    }
    with app.app_context():
        db.session.add_all([
            Player(name=player_name, team_id=1)
            for player_name in alignment.values()
        ])
        db.session.add(Game(
            id=14,
            date=datetime(2026, 8, 18),
            opponent='Starting Defense Test',
            team_id=1,
        ))
        db.session.commit()

    response = client.post('/api/starting-defense-template/save', json={
        'title': 'Standard Starters',
        'innings': {'1': alignment},
    })

    assert response.status_code == 200
    payload = response.get_json()
    template_id = payload['id']
    assert payload['display_title'] == 'Standard Starters'
    assert payload['rotation']['title'] == 'DEFENSE PRESET — Standard Starters'
    assert payload['rotation']['innings'] == {'1': alignment}
    assert 'P' not in payload['rotation']['innings']['1']

    with app.app_context():
        saved = db.session.get(Rotation, template_id)
        assert saved.title == 'DEFENSE PRESET — Standard Starters'
        assert saved.innings == {'1': alignment}

    editor = client.get(f'/starting-defense-template/{template_id}')
    assert editor.status_code == 200
    editor_html = editor.get_data(as_text=True)
    assert 'Pitcher is optional' in editor_html
    assert 'Standard Starters' in editor_html

    game_data = client.get('/api/game_data/14')
    assert game_data.status_code == 200
    game_templates = game_data.get_json()['rotation_templates']
    assert any(template['id'] == template_id for template in game_templates)

    incomplete = dict(alignment)
    incomplete.pop('1B')
    rejected = client.post('/api/starting-defense-template/save', json={
        'title': 'Incomplete Defense',
        'innings': {'1': incomplete},
    })
    assert rejected.status_code == 400
    assert 'Fill 1B before saving' in rejected.get_json()['message']


def test_game_management_assets_keep_readiness_compact_without_ambiguous_primary_fill():
    project_root = Path(__file__).resolve().parents[1]
    navigation = (project_root / 'static/js/navigation_v2.js').read_text()
    game_logic = (project_root / 'static/js/game_logic.js').read_text()
    live_game = (project_root / 'static/js/live_game_v2.js').read_text()
    pitching_rules = (project_root / 'static/js/game_pitching_rule_picker.js').read_text()
    defense = (project_root / 'static/js/live_game_board_prep.js').read_text()
    season_management = (project_root / 'static/js/season_management_v2.js').read_text()

    assert 'game_prep_readiness.js' not in navigation
    assert "typeof io === 'function' ? io() : null" in game_logic
    assert '/api/toggle_live_game' not in game_logic
    assert "typeof io !== 'function'" in live_game
    assert 'game-pitch-rule-editor-v2" hidden' in pitching_rules
    assert 'Quick-Fill Primaries' not in defense
    assert 'pde-primary-fill' not in defense
    assert 'fillPrimaryPositions' not in defense
    assert '/api/starting-defense-template/save' in defense
    assert 'pos !== \'P\'' in defense
    assert '/starting-defense-template/new' in season_management
    assert "window.location.replace('/game-day')" in navigation
    assert "moreLink('/game-day', 'calendar3', 'Schedule'" in navigation


def test_pitch_target_scope_is_explicit_and_game_is_team_scoped(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    from db import db
    from models import Game, Player, PlayerPitchTarget, Team

    with app.app_context():
        db.session.add_all([
            Player(id=41, name='Target Pitcher', pitcher_role='Starter', team_id=1),
            Game(id=41, date=datetime(2026, 8, 23), opponent='Target Opponent', team_id=1),
            Team(
                id=2,
                team_name='Other Target Team',
                registration_code='other-target-code',
                age_group='12U',
                pitching_rule_set='MLB Pitch Smart',
                outfielder_count=3,
                timezone='America/Indiana/Indianapolis',
            ),
            Game(id=42, date=datetime(2026, 8, 24), opponent='Other Team Game', team_id=2),
        ])
        db.session.commit()

    invalid_date = client.post('/save_player_target', json={
        'player_id': 41,
        'local_date': 'next Sunday',
        'target_pitches': 35,
    })
    assert invalid_date.status_code == 400

    cross_team_game = client.post('/save_player_target', json={
        'player_id': 41,
        'local_date': '2026-08-24',
        'game_id': 42,
        'target_pitches': 35,
    })
    assert cross_team_game.status_code == 404

    saved = client.post('/save_player_target', json={
        'player_id': 41,
        'local_date': '2026-08-01',
        'game_id': 41,
        'target_pitches': 42,
        'reason': ' Short start ',
    })
    assert saved.status_code == 200

    with app.app_context():
        target = db.session.query(PlayerPitchTarget).filter_by(player_id=41, game_id=41).one()
        assert target.local_date == '2026-08-23'
        assert target.target_pitches == 42
        assert target.reason == 'Short start'


def test_pitching_page_explains_target_scope(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    from db import db
    from models import Player

    with app.app_context():
        db.session.add(Player(id=51, name='Scope Pitcher', pitcher_role='Starter', team_id=1))
        db.session.commit()

    response = client.get('/pitching')

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Pitch targets are optional coaching plans.' in html
    assert 'Targets count game pitches only and do not change official eligibility.' in html
    assert 'Entire game day' in html
    assert 'One scheduled game' in html
    assert 'id="targetScopeInput"' in html
    assert 'id="targetGameInput"' in html
