from types import SimpleNamespace

import pytest


def _build_app(monkeypatch):
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')

    from app import create_app

    app = create_app()
    app.config.update(TESTING=True)
    return app


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

    with client.session_transaction() as session:
        session['logged_in'] = True
        session['username'] = 'coach'
        session['team_id'] = 1
        session['role'] = 'Head Coach'

    response = client.post('/toggle_live_game', json={'game_id': 1, 'is_live': True})

    assert response.status_code == 410
    assert 'older CoachBoard client' in response.get_json()['message']


def test_head_coach_cannot_forge_super_admin_assignment(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()

    with client.session_transaction() as session:
        session['logged_in'] = True
        session['username'] = 'coach'
        session['team_id'] = 1
        session['role'] = 'Head Coach'

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

    with client.session_transaction() as session:
        session['logged_in'] = True
        session['username'] = 'coach'
        session['team_id'] = 1
        session['role'] = 'Head Coach'

    response = client.get('/delete_player/1', headers={'Sec-Fetch-Site': 'cross-site'})

    assert response.status_code == 403
    assert 'Cross-site destructive request blocked' in response.get_json()['message']


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
