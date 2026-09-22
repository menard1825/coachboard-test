"""Page-level equivalence for the Postgame Follow-Up section.

The previous implementation of the loop is kept here as an oracle: it calls
_readiness_for_game() and keeps the full payload, exactly as the code did
before the classifier existed. Every assertion compares the shipped page
against that oracle through the real view and the real template, so "the cheap
path renders the same page" is measured rather than argued.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import event as sa_event
from werkzeug.security import generate_password_hash


ALIGNMENT = {
    'P': 'Pitcher Pat', 'C': 'Catcher Cole', '1B': 'First Frank',
    '2B': 'Second Sam', '3B': 'Third Theo', 'SS': 'Shortstop Shawn',
    'LF': 'Left Lee', 'CF': 'Center Casey', 'RF': 'Right Riley',
}
NAMES = list(ALIGNMENT.values())

# Status recipes built from valid application data.
PAST = dict(events=[], end_game=False, outings=[])
NEEDS_POSTGAME = dict(events=[1, 2], end_game=False, outings=[])
GC_PENDING = dict(events=[1, 2], end_game=True, outings=[])
COMPLETE = dict(events=[1, 2], end_game=True, outings=['Pitcher Pat', 'Left Lee'])


def _with_pitcher(name):
    out = dict(ALIGNMENT)
    out['P'] = name
    return out


def scenario_a():
    return [dict(day_offset=offset, opponent=f'Upcoming {offset}')
            for offset in (1, 3, 5, 8, 12)]


def scenario_b():
    return ([dict(day_offset=0, opponent='Today')]
            + [dict(day_offset=offset, opponent=f'Upcoming {offset}')
               for offset in (2, 4, 7)])


def scenario_c():
    return ([dict(day_offset=0, opponent='Today Completed', **COMPLETE)]
            + [dict(day_offset=offset, opponent=f'Upcoming {offset}')
               for offset in (2, 5)])


def scenario_d():
    games = [dict(day_offset=-(index + 1), opponent=f'History {index}',
                  **(NEEDS_POSTGAME if index % 3 == 0 else PAST))
             for index in range(12)]
    games.append(dict(day_offset=3, opponent='Upcoming'))
    return games


def scenario_e():
    """20 candidates; the six qualifying ones are the oldest, forcing a full scan."""
    games = [dict(day_offset=-(index + 1), opponent=f'Recent {index}', **PAST)
             for index in range(14)]
    games += [dict(day_offset=-(15 + index), opponent=f'Old {index}',
                   **NEEDS_POSTGAME) for index in range(6)]
    return games


def scenario_mixed_statuses():
    """Both follow-up statuses on one page, so the template renders both rows."""
    return [
        dict(day_offset=-1, opponent='Pending GC', **GC_PENDING),
        dict(day_offset=-2, opponent='Unfinished', **NEEDS_POSTGAME),
        dict(day_offset=-3, opponent='Done', **COMPLETE),
        dict(day_offset=-4, opponent='Old', **PAST),
    ]


def scenario_more_than_six():
    return [dict(day_offset=-(index + 1), opponent=f'Needs {index}',
                 **NEEDS_POSTGAME) for index in range(9)]


def scenario_fewer_than_six():
    games = [dict(day_offset=-(index + 1), opponent=f'Needs {index}',
                  **NEEDS_POSTGAME) for index in range(3)]
    games += [dict(day_offset=-(10 + index), opponent=f'Old {index}', **PAST)
              for index in range(5)]
    return games


def scenario_none_qualify():
    return [dict(day_offset=-(index + 1), opponent=f'Old {index}', **PAST)
            for index in range(8)]


SCENARIOS = [
    ('A simple future', scenario_a),
    ('B typical game day', scenario_b),
    ('C completed today', scenario_c),
    ('D follow-up heavy', scenario_d),
    ('E worst-case 20 scan', scenario_e),
]
SCENARIO_IDS = [label for label, _ in SCENARIOS]


def _build_app(monkeypatch, spec):
    monkeypatch.setenv('SECRET_KEY', 'game-day-page-followup-test')
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
        team = Team(id=1, team_name='Page Follow-Up', registration_code='page-fu',
                    age_group='11U', pitching_rule_set='MLB Pitch Smart',
                    outfielder_count=3, timezone='America/Indiana/Indianapolis')
        db.session.add_all([
            team,
            User(id=1, username='page-coach', full_name='Page Coach',
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
                is_live=item.get('is_live', False), live_current_inning='1'))
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
        session['username'] = 'page-coach'
        session['role'] = 'Head Coach'


def _legacy_classifier(game_day):
    """The pre-classifier loop body, kept as an oracle."""
    def oracle(game, team_id):
        from db import db
        from models import Team
        team = db.session.get(Team, team_id)
        readiness = game_day._readiness_for_game(game, team)
        if readiness['status'] in {'GC STATS PENDING', 'NEEDS POSTGAME'}:
            return readiness
        return None
    return oracle


def _capture_context(app, client, monkeypatch):
    """Render /game-day and capture what the view handed the template."""
    from flask import template_rendered

    captured = {}

    def record(sender, template, context, **extra):
        captured['template'] = template.name
        captured['context'] = context

    template_rendered.connect(record, app)
    try:
        response = client.get('/game-day')
    finally:
        template_rendered.disconnect(record, app)

    context = captured.get('context', {})
    return {
        'status_code': response.status_code,
        'body': response.get_data(as_text=True),
        'followup_ids': [item['game'].id for item in context.get('followup_cards', [])],
        'followup_statuses': [item['readiness']['status']
                              for item in context.get('followup_cards', [])],
        'followup_missing': [list(item['readiness'].get('pitching_missing', []))
                             for item in context.get('followup_cards', [])],
        'focus_ids': [item['game'].id for item in context.get('game_cards', [])],
        'focus_label': context.get('focus_label'),
        'upcoming_ids': [game.id for game in context.get('upcoming', [])],
        'past_ids': [game.id for game in context.get('past_games', [])],
    }


def _before_and_after(monkeypatch, spec):
    import blueprints.game_day as game_day

    app = _build_app(monkeypatch, spec)
    client = app.test_client()
    _login(client)

    after = _capture_context(app, client, monkeypatch)

    monkeypatch.setattr(game_day, 'build_game_followup_status',
                        _legacy_classifier(game_day))
    before = _capture_context(app, client, monkeypatch)
    monkeypatch.undo()

    return before, after, app, client


# --- page equivalence -----------------------------------------------------

@pytest.mark.parametrize('label,builder', SCENARIOS, ids=SCENARIO_IDS)
def test_page_is_equivalent_to_the_full_readiness_loop(monkeypatch, label, builder):
    before, after, _, _ = _before_and_after(monkeypatch, builder())

    assert after['status_code'] == before['status_code'] == 200
    assert after['followup_ids'] == before['followup_ids']
    assert len(after['followup_ids']) == len(before['followup_ids'])
    assert after['followup_statuses'] == before['followup_statuses']
    assert after['followup_missing'] == before['followup_missing']
    assert after['focus_ids'] == before['focus_ids']
    assert after['focus_label'] == before['focus_label']
    assert after['upcoming_ids'] == before['upcoming_ids']
    assert after['past_ids'] == before['past_ids']


def test_rendered_followup_section_is_byte_identical(monkeypatch):
    """Both follow-up statuses on one page, compared as rendered HTML."""
    before, after, _, _ = _before_and_after(monkeypatch, scenario_mixed_statuses())

    def section(body):
        start = body.index('Postgame Follow-Up')
        end = body.index('Coming Up', start) if 'Coming Up' in body[start:] else len(body)
        return body[start:end]

    assert 'Postgame Follow-Up' in after['body']
    assert section(after['body']) == section(before['body'])

    rendered = section(after['body'])
    assert 'Enter Stats' in rendered
    assert 'Finish Game' in rendered
    assert 'Need GameChanger numbers for' in rendered
    assert 'This game still needs to be finished in CoachBoard.' in rendered
    assert after['followup_statuses'] == ['GC STATS PENDING', 'NEEDS POSTGAME']


def test_socket_room_list_still_includes_followup_game_ids(monkeypatch):
    _, after, _, _ = _before_and_after(monkeypatch, scenario_mixed_statuses())
    for game_id in after['followup_ids']:
        assert f'{game_id},' in after['body']


# --- break at six ---------------------------------------------------------

def test_more_than_six_qualifying_keeps_the_first_six(monkeypatch):
    before, after, _, _ = _before_and_after(monkeypatch, scenario_more_than_six())
    assert len(after['followup_ids']) == 6
    assert after['followup_ids'] == before['followup_ids']


def test_fewer_than_six_qualifying_keeps_all_of_them(monkeypatch):
    before, after, _, _ = _before_and_after(monkeypatch, scenario_fewer_than_six())
    assert len(after['followup_ids']) == 3
    assert after['followup_ids'] == before['followup_ids']


def test_qualifying_games_late_in_the_scan_are_still_found(monkeypatch):
    before, after, _, _ = _before_and_after(monkeypatch, scenario_e())
    assert len(after['followup_ids']) == 6
    assert after['followup_ids'] == before['followup_ids']


def test_no_qualifying_games_gives_an_empty_section(monkeypatch):
    before, after, _, _ = _before_and_after(monkeypatch, scenario_none_qualify())
    assert after['followup_ids'] == []
    assert before['followup_ids'] == []
    assert 'Postgame Follow-Up' not in after['body']


# --- page SQL -------------------------------------------------------------

def _measure_page(app, client):
    from db import db

    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if not statement.strip().upper().startswith('PRAGMA '):
            statements.append(statement)

    with app.app_context():
        engine = db.session.get_bind()
    sa_event.listen(engine, 'before_cursor_execute', capture)
    try:
        response = client.get('/game-day')
    finally:
        sa_event.remove(engine, 'before_cursor_execute', capture)

    writes = [s for s in statements
              if s.strip().upper().startswith(('INSERT', 'UPDATE', 'DELETE'))]
    return response, statements, writes


# Measured, not predicted. See the slice report for before/after figures.
MAX_PAGE_STATEMENTS = {
    'A simple future': 28,
    'B typical game day': 26,
    'C completed today': 25,
    'D follow-up heavy': 60,
    'E worst-case 20 scan': 68,
}


@pytest.mark.parametrize('label,builder', SCENARIOS, ids=SCENARIO_IDS)
def test_page_query_budget(monkeypatch, label, builder, capsys):
    app = _build_app(monkeypatch, builder())
    client = app.test_client()
    _login(client)
    assert client.get('/game-day').status_code == 200

    response, statements, writes = _measure_page(app, client)

    with capsys.disabled():
        print(f'\n  [{label}] {len(statements)} statements, writes={len(writes)}')

    assert response.status_code == 200
    assert writes == []
    assert len(statements) <= MAX_PAGE_STATEMENTS[label], (
        f'{label}: {len(statements)} statements exceeds '
        f'{MAX_PAGE_STATEMENTS[label]}'
    )
