"""Classic / Updated view: one coach's own choice, per team, on the server.

The choice lives on that coach's TeamMembership row, so it follows them to
every device and never touches another coach. It only picks a presentation:
a live game is always Updated, and nobody is offered Classic until
COACHBOARD_CLASSIC_VIEW allows it.
"""

import re
from datetime import datetime, timedelta

import pytest
from werkzeug.security import generate_password_hash


def _build_app(monkeypatch, access=None):
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')
    if access is None:
        monkeypatch.delenv('COACHBOARD_CLASSIC_VIEW', raising=False)
    else:
        monkeypatch.setenv('COACHBOARD_CLASSIC_VIEW', access)

    from app import create_app
    from db import db
    from models import Game, Team, TeamMembership, User

    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        db.create_all()
        db.session.add_all([
            Team(id=1, team_name='Hawks', registration_code='hawks', age_group='10U',
                 pitching_rule_set='USSSA', outfielder_count=3),
            Team(id=2, team_name='Owls', registration_code='owls', age_group='10U',
                 pitching_rule_set='USSSA', outfielder_count=3),
        ])
        for uid, name in ((1, 'ann'), (2, 'bo'), (3, 'admin'), (4, 'gc')):
            db.session.add(User(id=uid, username=name, full_name=name.title(), email=f'{name}@example.com',
                                password_hash=generate_password_hash('password123')))
        db.session.flush()
        db.session.add_all([
            TeamMembership(user_id=1, team_id=1, role='Head Coach', player_order=[]),
            TeamMembership(user_id=1, team_id=2, role='Assistant Coach', player_order=[]),
            TeamMembership(user_id=2, team_id=1, role='Assistant Coach', player_order=[]),
            TeamMembership(user_id=3, team_id=1, role='Super Admin', player_order=[]),
            TeamMembership(user_id=4, team_id=1, role='Game Changer', player_order=[]),
            Game(id=10, date=datetime.now() + timedelta(days=1), opponent='Upcoming', team_id=1),
            Game(id=11, date=datetime.now(), opponent='Live Now', team_id=1, is_live=True,
                 live_current_inning='2'),
        ])
        db.session.commit()
    return app


ROLES = {'ann': 'Head Coach', 'bo': 'Assistant Coach', 'admin': 'Super Admin', 'gc': 'Game Changer'}


def _client(app, username, team_id=1, role=None):
    client = app.test_client()
    with client.session_transaction() as session:
        session.update(logged_in=True, username=username, full_name=username.title(),
                       team_id=team_id, role=role or ROLES[username], player_order=[])
    return client


def _set(client, view, **kwargs):
    return client.post('/api/account/view', json={'view': view, **kwargs})


def _body(client, path='/game/10'):
    html = client.get(path).get_data(as_text=True)
    tag = re.search(r'<body[^>]*>', html).group(0)
    return {
        'view': re.search(r'data-cb-view="([^"]*)"', tag).group(1),
        'choice': re.search(r'data-cb-view-choice="([^"]*)"', tag).group(1),
        'menu': 'data-cb-view-set="classic"' in html,
        'notice': 'data-cb-view-notice' in html,
        'script': 'js/ui_view_switch.js' in html,
    }


def _stored(app, user_id, team_id):
    from db import db
    from models import TeamMembership
    with app.app_context():
        return db.session.query(TeamMembership).filter_by(user_id=user_id, team_id=team_id).one().ui_view


def test_default_is_updated_and_classic_is_not_offered(monkeypatch):
    app = _build_app(monkeypatch)
    ann = _client(app, 'ann')
    page = _body(ann)
    assert page == {'view': 'updated', 'choice': 'updated', 'menu': False, 'notice': False, 'script': False}
    response = _set(ann, 'classic')
    assert response.status_code == 403
    assert _stored(app, 1, 1) is None


def test_choice_is_per_coach_per_team_and_follows_the_coach(monkeypatch):
    app = _build_app(monkeypatch, 'all')
    ann, bo = _client(app, 'ann'), _client(app, 'bo')
    assert _body(ann)['menu'] and _body(bo)['menu']

    assert _set(ann, 'classic').get_json() == {'status': 'success', 'view': 'classic'}
    assert _stored(app, 1, 1) == 'classic'
    page = _body(ann)
    assert (page['view'], page['choice'], page['notice']) == ('classic', 'classic', True)
    assert _body(ann, '/')['view'] == 'classic'

    # Another coach on the same team: unchanged.
    assert _body(bo)['view'] == 'updated' and _stored(app, 2, 1) is None
    # The same coach on their other team: unchanged.
    assert _body(_client(app, 'ann', team_id=2, role='Assistant Coach'), '/')['view'] == 'updated'
    assert _stored(app, 1, 2) is None
    # The same coach on another device (a fresh session): Classic.
    assert _body(_client(app, 'ann'))['choice'] == 'classic'

    # Back to Updated: stored as the default again.
    assert _set(ann, 'updated').status_code == 200
    assert _stored(app, 1, 1) is None
    assert _body(ann)['view'] == 'updated'


def test_a_live_game_is_always_updated(monkeypatch):
    app = _build_app(monkeypatch, 'all')
    ann = _client(app, 'ann')
    _set(ann, 'classic')
    live = _body(ann, '/game/11')
    assert (live['view'], live['choice'], live['notice']) == ('updated', 'classic', False)
    assert live['script']  # still able to switch from here
    assert _body(ann, '/game/10')['view'] == 'classic'


@pytest.mark.parametrize('tool', ['pitching', 'edit'])
def test_a_completed_games_own_tools_are_always_updated(monkeypatch, tool):
    # Final pitch counts and the completed-game review run on the live
    # screens, so they stay Updated whatever the coach chose.
    app = _build_app(monkeypatch, 'all')
    ann = _client(app, 'ann')
    _set(ann, 'classic')
    assert _body(ann, f'/game/10?{tool}=1')['view'] == 'updated'
    assert _body(ann, f'/game/10?{tool}=0')['view'] == 'classic'


def test_super_admin_preview_offers_it_to_super_admins_only(monkeypatch):
    app = _build_app(monkeypatch, 'super-admin')
    admin, ann = _client(app, 'admin'), _client(app, 'ann')
    assert _body(admin)['menu'] and not _body(ann)['menu']
    assert _set(ann, 'classic').status_code == 403
    assert _set(admin, 'classic').status_code == 200
    assert _body(admin)['view'] == 'classic'
    assert _body(ann)['view'] == 'updated'


def test_a_stored_choice_is_ignored_while_classic_is_off(monkeypatch):
    app = _build_app(monkeypatch, 'all')
    _set(_client(app, 'ann'), 'classic')
    assert _stored(app, 1, 1) == 'classic'

    app_off = _build_app(monkeypatch, 'off')
    from db import db
    from models import TeamMembership
    with app_off.app_context():
        db.session.query(TeamMembership).filter_by(user_id=1, team_id=1).one().ui_view = 'classic'
        db.session.commit()
    page = _body(_client(app_off, 'ann'))
    assert (page['view'], page['choice'], page['menu']) == ('updated', 'updated', False)


@pytest.mark.parametrize('access', ['off', 'all'])
def test_game_changer_is_never_offered_it(monkeypatch, access):
    app = _build_app(monkeypatch, access)
    gc = _client(app, 'gc')
    assert _set(gc, 'classic').status_code == 403
    assert _stored(app, 4, 1) is None


def test_only_the_signed_in_coach_own_membership_can_change(monkeypatch):
    app = _build_app(monkeypatch, 'all')
    ann = _client(app, 'ann')
    # Any user or team in the request is ignored: it changes ann's Hawks row.
    assert _set(ann, 'classic', user_id=2, team_id=2).status_code == 200
    assert (_stored(app, 1, 1), _stored(app, 2, 1), _stored(app, 1, 2)) == ('classic', None, None)

    assert ann.post('/api/account/view', data={'view': 'classic'}).status_code == 415
    assert _set(ann, 'sideways').status_code == 400
    cross = ann.post('/api/account/view', json={'view': 'updated'},
                     headers={'Origin': 'https://evil.example'})
    assert cross.status_code == 403
    assert _stored(app, 1, 1) == 'classic'

    anonymous = app.test_client().post('/api/account/view', json={'view': 'classic'})
    assert anonymous.status_code == 401


def test_the_migration_adds_and_removes_only_the_column(monkeypatch, tmp_path):
    """Additive and reversible, on a database with data in it."""
    import sqlite3

    from flask_migrate import downgrade, upgrade

    path = tmp_path / 'mig.db'
    monkeypatch.setenv('SECRET_KEY', 'x')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{path}')
    from app import create_app
    app = create_app()
    with app.app_context():
        upgrade(revision='b6e2d8f4a1c7')
    con = sqlite3.connect(path)
    con.execute("INSERT INTO teams (id, team_name, registration_code, display_coach_names, age_group, "
                "pitching_rule_set, outfielder_count) VALUES (1,'T','x',0,'10U','USSSA',3)")
    con.execute("INSERT INTO users (id, username, password_hash) VALUES (1,'ann','h')")
    con.execute("INSERT INTO team_memberships (id, user_id, team_id, role, player_order) VALUES (1,1,1,'Head Coach','[\"x\"]')")
    con.commit()
    before = con.execute('SELECT * FROM team_memberships').fetchall()
    con.close()

    def columns():
        with sqlite3.connect(path) as c:
            return [r[1] for r in c.execute('PRAGMA table_info(team_memberships)')]

    with app.app_context():
        upgrade(revision='c7a3e9f1b2d4')
    assert columns()[-1] == 'ui_view'
    with sqlite3.connect(path) as c:
        assert c.execute('SELECT * FROM team_memberships').fetchall() == [before[0] + (None,)]
        assert c.execute('SELECT version_num FROM alembic_version').fetchone()[0] == 'c7a3e9f1b2d4'

    with app.app_context():
        downgrade(revision='b6e2d8f4a1c7')
    assert 'ui_view' not in columns()
    with sqlite3.connect(path) as c:
        assert c.execute('SELECT * FROM team_memberships').fetchall() == before
