from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
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


def test_game_management_assets_keep_readiness_compact_without_ambiguous_primary_fill():
    project_root = Path(__file__).resolve().parents[1]
    navigation = (project_root / 'static/js/navigation_v2.js').read_text()
    pitching_rules = (project_root / 'static/js/game_pitching_rule_picker.js').read_text()
    defense = (project_root / 'static/js/live_game_board_prep.js').read_text()

    assert 'game_prep_readiness.js' not in navigation
    assert 'game-pitch-rule-editor-v2" hidden' in pitching_rules
    assert 'Quick-Fill Primaries' not in defense
    assert 'pde-primary-fill' not in defense
    assert 'fillPrimaryPositions' not in defense
