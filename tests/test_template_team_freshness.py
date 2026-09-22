"""The template context processor refreshes Teams -- and only Teams.

inject_team_info() used to call db.session.expire_all() before loading the
header's Team. That did keep current_team and available_teams fresh, but it
also invalidated every other object the view had already loaded, so each
attribute the template then read cost another SELECT.

These tests pin both halves of the replacement:

  * the freshness the old code plausibly existed for is still there --
    populate_existing() overwrites the Team rows even when a stale copy is
    already sitting in the identity map (tests 1 and 2);
  * nothing else is expired, and the processor issues no writes (tests 3
    and 4).

Each test is written so that deleting the single line it protects makes it
fail. The mutation each one answers to is named in its docstring.
"""

import pytest
from sqlalchemy import event as sa_event
from werkzeug.security import generate_password_hash


ORIGINAL_TEAM_NAME = 'Original Dugout'
ORIGINAL_OTHER_NAME = 'Original Other'
REFRESHED_TEAM_NAME = 'Refreshed Dugout'
REFRESHED_OTHER_NAME = 'Refreshed Other'


class Recorder:
    """Count the statements a block of work issues, by kind."""

    def __init__(self):
        self.on = False
        self.statements = []

    def before(self, conn, cursor, statement, parameters, context, executemany):
        if self.on:
            self.statements.append(' '.join(statement.split()))

    def selects(self, table=None):
        return [s for s in self.statements
                if s.upper().startswith('SELECT')
                and (table is None or f'FROM {table} ' in s or s.endswith(f'FROM {table}'))]

    def writes(self):
        return [s for s in self.statements
                if s.upper().startswith(('INSERT', 'UPDATE', 'DELETE'))]


@pytest.fixture
def recording(app):
    """Attach a statement recorder to the app's engine for one test."""
    from db import db

    with app.app_context():
        engine = db.session.get_bind()
    recorder = Recorder()
    sa_event.listen(engine, 'before_cursor_execute', recorder.before)
    try:
        yield recorder
    finally:
        sa_event.remove(engine, 'before_cursor_execute', recorder.before)


@pytest.fixture
def app(monkeypatch):
    """A two-team app: the coach belongs to both, so the Switch Team menu renders."""
    monkeypatch.setenv('SECRET_KEY', 'template-team-freshness-test')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')

    from app import create_app
    from db import db
    from models import (Game, Lineup, LineupEntry, Player, Rotation, Team,
                        TeamMembership, User)

    created = create_app()
    created.config.update(TESTING=True)

    with created.app_context():
        db.create_all()
        db.session.add_all([
            Team(id=1, team_name=ORIGINAL_TEAM_NAME, registration_code='freshness-1',
                 age_group='11U', pitching_rule_set='MLB Pitch Smart',
                 outfielder_count=3, timezone='America/Indiana/Indianapolis'),
            Team(id=2, team_name=ORIGINAL_OTHER_NAME, registration_code='freshness-2',
                 age_group='12U', pitching_rule_set='MLB Pitch Smart',
                 outfielder_count=3, timezone='America/Indiana/Indianapolis'),
            User(id=1, username='freshness-coach', full_name='Freshness Coach',
                 password_hash=generate_password_hash('password123')),
        ])
        db.session.flush()
        db.session.add_all([
            TeamMembership(user_id=1, team_id=1, role='Head Coach', player_order=[]),
            TeamMembership(user_id=1, team_id=2, role='Head Coach', player_order=[]),
        ])
        db.session.add(Player(id=1, name='Pitcher Pat', number='1', team_id=1,
                              pitcher_role='Pitcher'))
        db.session.flush()

        from datetime import datetime, timedelta
        db.session.add(Game(id=500, date=datetime.now() - timedelta(days=1),
                            start_time='12:00', opponent='Yesterday', team_id=1,
                            is_live=False, live_current_inning='1'))
        db.session.add(Rotation(id=500, title='Rotation 500', innings={'1': {}},
                                associated_game_id=500, team_id=1))
        lineup = Lineup(id=500, title='Lineup 500', associated_game_id=500, team_id=1)
        db.session.add(lineup)
        db.session.flush()
        db.session.add(LineupEntry(lineup_id=500, player_id=1,
                                   player_name_snapshot='Pitcher Pat', batting_order=1))
        db.session.commit()

    return created


@pytest.fixture
def client(app):
    test_client = app.test_client()
    with test_client.session_transaction() as session:
        session['logged_in'] = True
        session['user_id'] = 1
        session['team_id'] = 1
        session['username'] = 'freshness-coach'
        session['role'] = 'Head Coach'
    return test_client


def _stale_bulk_update(team_id, new_name):
    """Change a Team row underneath any ORM copy already in the identity map.

    synchronize_session=False is the point: the UPDATE reaches the database
    and the in-session object keeps the old value, which is precisely the
    staleness the processor has to defeat.
    """
    from db import db
    from models import Team

    db.session.query(Team).filter(Team.id == team_id).update(
        {'team_name': new_name}, synchronize_session=False)


def _preload_then_stale(app, team_id, new_name):
    """Register a before_request hook that leaves `team_id` stale in-session.

    It runs before the view, so by the time inject_team_info() executes the
    identity map already holds a Team whose team_name is out of date. Without
    this, every request starts with an empty identity map and any load would
    be fresh by accident, so the test would not discriminate.
    """
    from db import db
    from models import Team

    @app.before_request
    def _make_stale():  # pragma: no cover - exercised through the client
        team = db.session.get(Team, team_id)
        assert team is not None
        _ = team.team_name
        _stale_bulk_update(team_id, new_name)


# --- 1. current_team ------------------------------------------------------

def test_current_team_is_refreshed_when_the_identity_map_is_stale(app):
    """Mutation: drop populate_existing=True from the current_team get.

    The session deliberately carries no username, so inject_team_info() takes
    only its first branch and the available_teams query never runs. That
    isolation is the point. Measured while writing this test: when a username
    IS present, the available_teams query returns the current team too, and
    its own .populate_existing() refreshes it -- so a test that keeps the
    username cannot tell the two lines apart, and would pass with this one
    deleted. A logged-in page always sends a username; this request shape is
    reachable only through the processor itself, which is exactly the unit
    the line belongs to.
    """
    from db import db
    from flask import render_template_string, session
    from models import Team

    with app.test_request_context('/'):
        session['team_id'] = 1

        team = db.session.get(Team, 1)
        assert team.team_name == ORIGINAL_TEAM_NAME
        _stale_bulk_update(1, REFRESHED_TEAM_NAME)
        assert team.team_name == ORIGINAL_TEAM_NAME, 'fixture did not create staleness'

        rendered = render_template_string(
            '{{ current_team.team_name }}|{{ available_teams is defined }}')

    assert rendered == f'{REFRESHED_TEAM_NAME}|False'


def test_current_team_is_refreshed_through_the_real_page_stack(app, client):
    """End-to-end cover for the same contract.

    Either populate_existing would satisfy this one, since the available
    teams include the current team; it is here so the freshness is pinned
    through the real guard, view and base.html rather than only through a
    synthetic request context.
    """
    _preload_then_stale(app, 1, REFRESHED_TEAM_NAME)

    response = client.get('/admin/settings')

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert REFRESHED_TEAM_NAME in body
    assert ORIGINAL_TEAM_NAME not in body


# --- 2. available_teams ---------------------------------------------------

def test_available_teams_objects_carry_the_refreshed_value(app):
    """Mutation: drop .populate_existing() from the available_teams query."""
    from db import db
    from flask import render_template_string, session
    from models import Team

    with app.test_request_context('/'):
        session['logged_in'] = True
        session['team_id'] = 1
        session['username'] = 'freshness-coach'

        other = db.session.get(Team, 2)
        assert other.team_name == ORIGINAL_OTHER_NAME
        _stale_bulk_update(2, REFRESHED_OTHER_NAME)
        assert other.team_name == ORIGINAL_OTHER_NAME, 'fixture did not create staleness'

        rendered = render_template_string(
            '{% for team in available_teams %}{{ team.team_name }}|{% endfor %}')

    assert REFRESHED_OTHER_NAME in rendered
    assert ORIGINAL_OTHER_NAME not in rendered


def test_switch_team_menu_shows_the_refreshed_name_of_another_team(app, client):
    """Mutation: drop .populate_existing() from the available_teams query.

    Scoped to base.html's Switch Team links. A bare substring search over the
    whole body would not do: /admin/settings lists teams from its own query,
    so the refreshed name appears there whether the menu is stale or not.
    """
    import re

    _preload_then_stale(app, 2, REFRESHED_OTHER_NAME)

    response = client.get('/admin/settings')

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    menu_links = re.findall(r'<a[^>]*switch_team[^>]*>.*?</a>', body, re.S)
    assert menu_links, 'the Switch Team menu did not render'
    menu = ' '.join(menu_links)
    assert REFRESHED_OTHER_NAME in menu
    assert ORIGINAL_OTHER_NAME not in menu


# --- 3. the processor stays read-only -------------------------------------

def test_context_processor_does_not_flush_unrelated_dirty_state(app, recording):
    """Mutation: drop `with db.session.no_autoflush`.

    The processor runs after the view function and immediately before the
    template executes. An autoflush there would push a view's unflushed edit
    to the database merely because the page chrome rendered.

    Recording is scoped to the render alone. Measured while writing this
    test: through a real client.get() the view's own queries autoflush the
    dirty object long before the processor is reached, so a whole-request
    recorder attributes the UPDATE to the view, not to the header. Isolating
    the render is what makes this test answer for the processor.

    The assertion is on the statement log and on the session still holding
    the edit afterwards -- not on the row's value once the request ends,
    which teardown's rollback would protect either way.
    """
    from db import db
    from flask import render_template_string, session
    from models import Game
    from sqlalchemy import inspect as sa_inspect

    with app.test_request_context('/'):
        session['logged_in'] = True
        session['team_id'] = 1
        session['username'] = 'freshness-coach'

        game = db.session.get(Game, 500)
        game.opponent = 'DIRTY AND UNFLUSHED'
        assert game in db.session.dirty, 'fixture did not create dirty state'

        recording.on = True
        try:
            render_template_string('{{ current_team.team_name }}')
        finally:
            recording.on = False

        assert recording.writes() == [], (
            'the context processor wrote to the database: %r' % (recording.writes(),))
        assert game in db.session.dirty, (
            'the context processor flushed an unrelated edit')
        assert sa_inspect(game).attrs.opponent.history.has_changes()

        db.session.rollback()


def test_the_context_processor_issues_no_writes_on_an_ordinary_page(app, client,
                                                                    recording):
    """The most direct statement of the contract: rendering never writes."""
    recording.on = True
    try:
        response = client.get('/admin/settings')
    finally:
        recording.on = False

    assert response.status_code == 200
    assert recording.writes() == []


# --- 4. nothing but Team is expired ---------------------------------------

def test_context_processor_does_not_expire_other_loaded_objects(app, recording):
    """Mutation: restore db.session.expire_all() at the top of the branch."""
    from db import db
    from flask import render_template_string, session
    from models import Game, Lineup, Player, Rotation
    from sqlalchemy import inspect as sa_inspect

    with app.test_request_context('/'):
        session['logged_in'] = True
        session['team_id'] = 1
        session['username'] = 'freshness-coach'

        game = db.session.get(Game, 500)
        player = db.session.get(Player, 1)
        rotation = db.session.get(Rotation, 500)
        lineup = db.session.get(Lineup, 500)
        loaded = [game, player, rotation, lineup]
        # Touch a scalar on each so they are fully loaded, not just identified.
        _ = (game.opponent, player.name, rotation.title, lineup.title)
        assert not any(sa_inspect(obj).expired for obj in loaded)

        render_template_string('{{ current_team.team_name }}')

        expired_after = {type(obj).__name__ for obj in loaded
                         if sa_inspect(obj).expired}
        assert expired_after == set(), (
            'the context processor expired unrelated objects: %r' % (expired_after,))

        # And the observable consequence: reading them again costs nothing.
        recording.on = True
        try:
            _ = (game.opponent, player.name, rotation.title, lineup.title)
        finally:
            recording.on = False

    assert recording.statements == [], (
        'scalar access after the context processor issued SQL: %r'
        % (recording.statements,))


def test_the_context_processor_itself_issues_at_most_two_statements(app, recording):
    """One Team get, one available_teams join. Nothing else belongs here."""
    from flask import render_template_string, session

    with app.test_request_context('/'):
        session['logged_in'] = True
        session['team_id'] = 1
        session['username'] = 'freshness-coach'

        recording.on = True
        try:
            render_template_string('{{ current_team.team_name }}')
        finally:
            recording.on = False

    assert len(recording.statements) <= 2, recording.statements
    assert recording.writes() == []
