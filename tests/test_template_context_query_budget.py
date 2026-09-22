"""Query budgets for pages that render the shared template header.

inject_team_info() used to call db.session.expire_all(), which invalidated
every object the view had already loaded. Each attribute the template then
read cost another SELECT, and the bill scaled with how much the page had
loaded -- worst on Game Day, which holds a Game per card.

These budgets are ceilings (`<=`), not equalities, so a later improvement
lands without editing this file. They exist to catch the reverse: a change
that puts blanket expiration, or anything else that re-reads loaded rows,
back into the render path.

Set COACHBOARD_PRINT_BUDGETS=1 to print the measured numbers instead of
only asserting on them.
"""

import os
import re
from datetime import datetime, timedelta

import pytest
from flask import before_render_template
from sqlalchemy import event as sa_event
from werkzeug.security import generate_password_hash


ALIGNMENT = {
    'P': 'Pitcher Pat', 'C': 'Catcher Cole', '1B': 'First Frank',
    '2B': 'Second Sam', '3B': 'Third Theo', 'SS': 'Shortstop Shawn',
    'LF': 'Left Lee', 'CF': 'Center Casey', 'RF': 'Right Riley',
}
NAMES = list(ALIGNMENT.values())

PAST = dict(events=[], end_game=False, outings=[])
NEEDS_POSTGAME = dict(events=[1, 2], end_game=False, outings=[])
COMPLETE = dict(events=[1, 2], end_game=True, outings=['Pitcher Pat', 'Left Lee'])


def _with_pitcher(name):
    out = dict(ALIGNMENT)
    out['P'] = name
    return out


# --- the audit's five Game Day scenarios ----------------------------------

def scenario_a():
    """Simple future schedule: no game today, several upcoming."""
    return [dict(day_offset=offset, opponent=f'Upcoming {offset}')
            for offset in (1, 3, 5, 8, 12)]


def scenario_b():
    """Typical game day: one game today, several upcoming, no follow-ups."""
    return ([dict(day_offset=0, opponent='Today')]
            + [dict(day_offset=offset, opponent=f'Upcoming {offset}')
               for offset in (2, 4, 7)])


def scenario_c():
    """Completed game today: the same-day history path."""
    return ([dict(day_offset=0, opponent='Today Completed', **COMPLETE)]
            + [dict(day_offset=offset, opponent=f'Upcoming {offset}')
               for offset in (2, 5)])


def scenario_d():
    """Follow-up heavy: 12 historical candidates, only some qualify."""
    games = [dict(day_offset=-(index + 1), opponent=f'History {index}',
                  **(NEEDS_POSTGAME if index % 3 == 0 else PAST))
             for index in range(12)]
    games.append(dict(day_offset=3, opponent='Upcoming'))
    return games


def scenario_e():
    """Worst case: 20 candidates, the six qualifying ones oldest, full scan."""
    games = [dict(day_offset=-(index + 1), opponent=f'Recent {index}', **PAST)
             for index in range(14)]
    games += [dict(day_offset=-(15 + index), opponent=f'Old {index}',
                   **NEEDS_POSTGAME) for index in range(6)]
    return games


def scenario_routes():
    """A schedule rich enough that the non-Game-Day pages have real content."""
    return ([dict(day_offset=0, opponent='Today', **COMPLETE)]
            + [dict(day_offset=-(index + 1), opponent=f'Past {index}',
                    **(NEEDS_POSTGAME if index % 2 == 0 else PAST))
               for index in range(8)]
            + [dict(day_offset=index + 1, opponent=f'Up {index}')
               for index in range(4)])


SCENARIOS = [
    ('A simple future', scenario_a),
    ('B typical game day', scenario_b),
    ('C completed today', scenario_c),
    ('D follow-up heavy', scenario_d),
    ('E worst-case 20 scan', scenario_e),
]
SCENARIO_IDS = [label for label, _ in SCENARIOS]

# Measured on these fixtures with the Team-only refresh in place. Ceilings,
# so a future reduction lands here without an edit.
#
# The "blanket" column is what the same fixture costs when a session-wide
# expire_all() is put back into the render path (test_blanket_expiration_...
# below measures it rather than trusting this comment). It runs one statement
# above the removed code's own total, because the processor now refreshes the
# Team before the blanket expires it again.
MAX_GAME_DAY_STATEMENTS = {          # blanket:
    'A simple future': 22,           #   28
    'B typical game day': 21,        #   26
    'C completed today': 21,         #   25
    'D follow-up heavy': 42,         #   56
    'E worst-case 20 scan': 42,      #   63
}
MAX_ROUTE_STATEMENTS = {             # blanket:
    '/': 6,                          #    7
    '/game-day': 37,                 #   51
    '/pitching': 10,                 #   27
    '/admin/users': 5,               #    8
    '/admin/settings': 5,            #    6
}

# Pages where the saving is large enough to be worth pinning as a saving,
# not just as a ceiling. Keyed by the minimum number of statements blanket
# expiration must cost over the shipped path.
MIN_SAVING = {'/game-day': 10, '/pitching': 10}


class Recorder:
    def __init__(self):
        self.on = False
        self.statements = []

    def before(self, conn, cursor, statement, parameters, context, executemany):
        if self.on:
            self.statements.append(' '.join(statement.split()))

    def writes(self):
        return [s for s in self.statements
                if s.upper().startswith(('INSERT', 'UPDATE', 'DELETE'))]


def _build_app(monkeypatch, spec):
    monkeypatch.setenv('SECRET_KEY', 'template-context-budget-test')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')

    from app import create_app
    from blueprints.fair_play import TeamPitchingSettings
    from db import db
    from game_day_helpers import team_now
    from models import (Game, GameRotationEvent, Lineup, LineupEntry,
                        PitchingOuting, Player, Rotation, Team, TeamMembership,
                        User)

    app = create_app()
    app.config.update(TESTING=True)

    with app.app_context():
        db.create_all()
        team = Team(id=1, team_name='Budget Dugout', registration_code='budget',
                    age_group='11U', pitching_rule_set='MLB Pitch Smart',
                    outfielder_count=3, timezone='America/Indiana/Indianapolis')
        db.session.add_all([
            team,
            User(id=1, username='budget-coach', full_name='Budget Coach',
                 password_hash=generate_password_hash('password123')),
        ])
        db.session.flush()
        db.session.add(TeamMembership(user_id=1, team_id=1, role='Head Coach',
                                      player_order=[]))
        db.session.add_all([
            Player(id=index + 1, name=name, number=str(index + 1), team_id=1,
                   pitcher_role='Pitcher')
            for index, name in enumerate(NAMES)
        ])
        db.session.add(TeamPitchingSettings(
            team_id=1, competition_default_rule='USSSA',
            arm_care_rule_set='MLB Pitch Smart'))
        db.session.commit()

        today = team_now(team).date()
        base = datetime.combine(today, datetime.min.time())

        for index, item in enumerate(spec):
            game_id = 4000 + index
            when = base + timedelta(days=item['day_offset'], hours=12)
            db.session.add(Game(
                id=game_id, date=when, start_time='12:00',
                opponent=item['opponent'], team_id=1,
                is_live=False, live_current_inning='1'))
            db.session.flush()
            db.session.add(Rotation(
                title=f'Rotation {game_id}',
                innings={str(n): dict(ALIGNMENT) for n in range(1, 7)},
                associated_game_id=game_id, team_id=1))
            lineup = Lineup(title=f'Lineup {game_id}',
                            associated_game_id=game_id, team_id=1)
            db.session.add(lineup)
            db.session.flush()
            for order, name in enumerate(NAMES, start=1):
                player = db.session.query(Player).filter_by(name=name).first()
                db.session.add(LineupEntry(
                    lineup_id=lineup.id, player_id=player.id,
                    player_name_snapshot=name, batting_order=order))

            sequence = 0
            for inning in item.get('events', []):
                sequence += 1
                db.session.add(GameRotationEvent(
                    inning=str(inning), sequence=sequence,
                    event_type='Pitcher Change',
                    before_alignment=_with_pitcher('Pitcher Pat'),
                    after_alignment=_with_pitcher('Left Lee'),
                    reverted=False, team_id=1, game_id=game_id))
            if item.get('end_game'):
                sequence += 1
                db.session.add(GameRotationEvent(
                    inning='6', sequence=sequence, event_type='End Game',
                    before_alignment=_with_pitcher('Left Lee'),
                    after_alignment=_with_pitcher('Left Lee'),
                    reverted=False, team_id=1, game_id=game_id))
            for pitcher in item.get('outings', []):
                player = db.session.query(Player).filter_by(name=pitcher).first()
                db.session.add(PitchingOuting(
                    date=when.date(), opponent=item['opponent'], pitches=40,
                    innings=2.0, pitcher_type='Starter', outing_type='Game',
                    team_id=1, player_id=player.id, game_id=game_id))
            db.session.commit()

    return app


def _login(client):
    with client.session_transaction() as session:
        session['logged_in'] = True
        session['user_id'] = 1
        session['team_id'] = 1
        session['username'] = 'budget-coach'
        session['role'] = 'Head Coach'


def _recorder(app):
    from db import db

    with app.app_context():
        engine = db.session.get_bind()
    recorder = Recorder()
    sa_event.listen(engine, 'before_cursor_execute', recorder.before)
    return engine, recorder


def _measure(app, client, path):
    """Warm once, then record one request."""
    engine, recorder = _recorder(app)
    try:
        client.get(path)
        recorder.on = True
        response = client.get(path)
        recorder.on = False
    finally:
        sa_event.remove(engine, 'before_cursor_execute', recorder.before)
    return response, recorder


def _by_table(statements):
    """Compact failure output: which tables the statements hit, and how often."""
    from collections import Counter
    tables = Counter(match.group(1) for match in
                     (re.search(r'\bFROM (\w+)', item) for item in statements)
                     if match)
    return dict(tables.most_common())


def _report(label, measured, ceiling):
    if os.environ.get('COACHBOARD_PRINT_BUDGETS'):
        print(f'BUDGET {label}: measured {measured}, ceiling {ceiling}', flush=True)


# --- Game Day A-E ---------------------------------------------------------

@pytest.mark.parametrize('label,builder', SCENARIOS, ids=SCENARIO_IDS)
def test_game_day_stays_within_its_query_budget(monkeypatch, label, builder):
    app = _build_app(monkeypatch, builder())
    client = app.test_client()
    _login(client)

    response, recorder = _measure(app, client, '/game-day')
    ceiling = MAX_GAME_DAY_STATEMENTS[label]
    _report(label, len(recorder.statements), ceiling)

    assert response.status_code == 200
    assert recorder.writes() == [], recorder.writes()
    assert len(recorder.statements) <= ceiling, (
        f'{label}: {len(recorder.statements)} statements, budget {ceiling}; '
        f'by table {_by_table(recorder.statements)}')


# --- /pitching and the other representative pages -------------------------

@pytest.mark.parametrize('path', sorted(MAX_ROUTE_STATEMENTS))
def test_representative_pages_stay_within_their_query_budget(monkeypatch, path):
    app = _build_app(monkeypatch, scenario_routes())
    client = app.test_client()
    _login(client)

    response, recorder = _measure(app, client, path)
    ceiling = MAX_ROUTE_STATEMENTS[path]
    _report(path, len(recorder.statements), ceiling)

    assert response.status_code == 200
    assert recorder.writes() == [], recorder.writes()
    assert len(recorder.statements) <= ceiling, (
        f'{path}: {len(recorder.statements)} statements, budget {ceiling}; '
        f'by table {_by_table(recorder.statements)}')


# --- rendered-output parity against blanket expiration --------------------

ISO = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?')


def _scrub(body):
    out = re.sub(r'content="\d{9,}"', 'content="TS"', body)
    out = re.sub(r'_t=\d{9,}', '_t=TS', out)
    out = re.sub(r'\?v=[^"\']+', '?v=V', out)
    return ISO.sub('ISO', out)


def _blanket_expire(sender, template, context, **extra):
    """Reproduce the old code's effect on what the template sees.

    Flask runs update_template_context() -- every context processor --
    before it sends before_render_template, so expiring here invalidates the
    identity map after inject_team_info() has loaded its Teams and before any
    template attribute is read. That is exactly what the removed
    db.session.expire_all() did to the render.
    """
    from db import db
    db.session.expire_all()


def _render_both_ways(app, client, path):
    plain = _scrub(client.get(path).get_data(as_text=True))
    before_render_template.connect(_blanket_expire, app)
    try:
        expired = _scrub(client.get(path).get_data(as_text=True))
    finally:
        before_render_template.disconnect(_blanket_expire, app)
    return plain, expired


@pytest.mark.parametrize('label,builder', SCENARIOS, ids=SCENARIO_IDS)
def test_game_day_renders_the_same_bytes_without_blanket_expiration(
        monkeypatch, label, builder):
    app = _build_app(monkeypatch, builder())
    client = app.test_client()
    _login(client)

    plain, expired = _render_both_ways(app, client, '/game-day')
    assert plain == expired


@pytest.mark.parametrize('path', sorted(MAX_ROUTE_STATEMENTS))
def test_pages_render_the_same_bytes_without_blanket_expiration(monkeypatch, path):
    app = _build_app(monkeypatch, scenario_routes())
    client = app.test_client()
    _login(client)

    plain, expired = _render_both_ways(app, client, path)
    assert plain == expired


# --- the follow-up section specifically -----------------------------------

def _capture_followup(app, client, expire_blanket=False):
    from flask import template_rendered

    captured = {}

    def record(sender, template, context, **extra):
        captured['context'] = context

    template_rendered.connect(record, app)
    if expire_blanket:
        before_render_template.connect(_blanket_expire, app)
    try:
        response = client.get('/game-day')
    finally:
        template_rendered.disconnect(record, app)
        if expire_blanket:
            before_render_template.disconnect(_blanket_expire, app)

    context = captured.get('context', {})
    cards = context.get('followup_cards', [])
    return {
        'status_code': response.status_code,
        'ids': [item['game'].id for item in cards],
        'statuses': [item['readiness']['status'] for item in cards],
        'missing': [list(item['readiness'].get('pitching_missing', []))
                    for item in cards],
    }


@pytest.mark.parametrize('label,builder', SCENARIOS, ids=SCENARIO_IDS)
def test_followup_cards_are_unchanged_without_blanket_expiration(
        monkeypatch, label, builder):
    """IDs, order, status and pitching_missing must all survive the change."""
    app = _build_app(monkeypatch, builder())
    client = app.test_client()
    _login(client)

    shipped = _capture_followup(app, client)
    reference = _capture_followup(app, client, expire_blanket=True)

    assert shipped['status_code'] == reference['status_code'] == 200
    assert shipped['ids'] == reference['ids']
    assert shipped['statuses'] == reference['statuses']
    assert shipped['missing'] == reference['missing']


def test_blanket_expiration_would_cost_measurably_more(monkeypatch):
    """The budgets above are justified by a measurement, not by a comment.

    Restoring a session-wide expire_all() to the render path has to show up
    as real extra statements on the two pages that motivated this change. If
    it ever does not, the budgets are pinning nothing and should be revisited.
    """
    app = _build_app(monkeypatch, scenario_routes())
    client = app.test_client()
    _login(client)

    for path, minimum in sorted(MIN_SAVING.items()):
        _, shipped = _measure(app, client, path)

        before_render_template.connect(_blanket_expire, app)
        try:
            _, blanket = _measure(app, client, path)
        finally:
            before_render_template.disconnect(_blanket_expire, app)

        saving = len(blanket.statements) - len(shipped.statements)
        _report(f'{path} saving', saving, minimum)
        assert saving >= minimum, (
            f'{path}: blanket expiration cost {len(blanket.statements)} vs '
            f'{len(shipped.statements)} shipped, a saving of only {saving}')
