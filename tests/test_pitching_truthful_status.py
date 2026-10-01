"""Pitching dates and what a pitcher's status says.

* A throwing date or game day is a calendar date stored at midnight. It is
  shown as that date -- not converted as a UTC timestamp, which turned an
  Oct 1 game into "Wednesday, 09/30/26, 08:00 PM" on the Pitching page.
* A pitcher on the mound in a live game, or who pitched in a started game
  whose counts aren't entered yet, is never "Ready · 0 pitches": the count
  is unknown (unrecorded_pitching), the card says "Pitching Now" or
  "Pitched today — count needed", and the pitcher is not counted eligible.
* A confirmed 0 and an entered count work as before. A count entered today
  also says when the pitcher can pitch next, the same day it is entered.
* A Pitch Smart advisory is guidance: the pitcher stays eligible, and the
  compact badge says ADVISORY, not OUT.
"""

import re
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from werkzeug.security import generate_password_hash

from utils import PITCHING_RULES, calculate_pitch_count_summary


TEAM_ID = 1
TZ = 'America/Indiana/Indianapolis'
RULES = dict(PITCHING_RULES['MLB Pitch Smart']['12U'], rule_set_name='MLB Pitch Smart')
TODAY = date(2026, 10, 1)


def _player(pid, name):
    return SimpleNamespace(id=pid, name=name)


def _outing(pid, day, pitches, *, game_id=None, unrecorded=False, pitching_now=False, kind='Game'):
    return SimpleNamespace(
        player_id=pid, date=datetime.combine(day, datetime.min.time()), pitches=pitches,
        innings=None, outing_type=kind, game_id=game_id, unrecorded=unrecorded,
        pitching_now=pitching_now,
    )


def _summary(outings, *, today=TODAY, current_game_id=None):
    roster = [_player(1, 'Hansen'), _player(2, 'Graham')]
    return calculate_pitch_count_summary(roster, outings, RULES, target_date=today,
                                         team_timezone=TZ, current_game_id=current_game_id)


# --- The summary (pure) ----------------------------------------------------------------------

def test_pitching_now_is_not_ready_and_not_zero():
    hansen = _summary([_outing(1, TODAY, None, game_id=9, unrecorded=True, pitching_now=True)])['Hansen']
    assert hansen['workload_state'] == 'pitching_now'
    assert hansen['status'] == 'Pitch Count Incomplete'        # not Available
    assert hansen['daily'] is None and hansen['official_daily_pitches'] is None
    assert hansen['status_detail'] == 'Pitching now. Enter the pitch count when the game ends.'
    named = _summary([SimpleNamespace(**dict(vars(_outing(1, TODAY, None, game_id=9, unrecorded=True,
                                                          pitching_now=True)), opponent='Nitro'))])
    assert named['Hansen']['status_detail'] == 'Pitching now vs Nitro. Enter the pitch count when the game ends.'
    assert hansen['last_outing_display'] == 'Thu, Oct 01'


def test_pitched_earlier_with_no_count_says_count_needed():
    summary = _summary([_outing(1, TODAY, None, game_id=9, unrecorded=True)])
    assert summary['Hansen']['workload_state'] == 'count_needed'
    assert summary['Hansen']['status_detail'] == 'Pitched today — count needed.'
    assert summary['Hansen']['daily'] is None
    # Graham did not pitch: still plainly available.
    assert summary['Graham']['status'] == 'Available' and summary['Graham']['workload_state'] is None


def test_an_earlier_unfinished_game_names_its_day():
    hansen = _summary([_outing(1, TODAY - timedelta(days=2), None, game_id=9, unrecorded=True)])['Hansen']
    assert hansen['status_detail'] == 'Pitched Tue, Sep 29 — count needed.'


def test_a_confirmed_zero_is_zero():
    hansen = _summary([_outing(1, TODAY, 0, game_id=9)])['Hansen']
    assert hansen['daily'] == 0 and hansen['workload_state'] is None
    assert hansen['next_available_after_today'] is None


def test_an_entered_count_today_says_when_next():
    # 58 pitches (51-65): 3 days of rest under Pitch Smart 12U.
    hansen = _summary([_outing(1, TODAY, 58, game_id=9)])['Hansen']
    assert hansen['daily'] == 58
    assert hansen['rest_days_after_today'] == 3
    assert hansen['next_available_after_today'] == 'Mon, Oct 05'
    # The same rule, seen from the scheduled game dates.
    assert _summary([_outing(1, TODAY, 58, game_id=9)], today=date(2026, 10, 4))['Hansen']['status'] == 'Resting'
    assert _summary([_outing(1, TODAY, 58, game_id=9)], today=date(2026, 10, 5))['Hansen']['status'] == 'Available'


def test_a_saved_count_beats_a_placeholder_for_another_game():
    # A recorded game earlier today plus a live game now: still unknown.
    hansen = _summary([
        _outing(1, TODAY, 30, game_id=8),
        _outing(1, TODAY, None, game_id=9, unrecorded=True, pitching_now=True),
    ])['Hansen']
    assert hansen['workload_state'] == 'pitching_now' and hansen['daily'] is None


# --- Started games with no counts (database) -------------------------------------------------

NAMES = ['Hansen', 'Graham', 'Cole', 'Drew', 'Eli', 'Finn', 'Gray', 'Harper', 'Indy', 'Jules']
POSITIONS = ['P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF']
FIELD = dict(zip(POSITIONS, NAMES))
GRAHAM_P = dict(FIELD, P='Graham', C='Jules')


def _local_today():
    return datetime.now(ZoneInfo(TZ)).date()


@pytest.fixture(name='app')
def _app(monkeypatch, tmp_path):
    monkeypatch.setenv('SECRET_KEY', 'pitching-truth-test')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{tmp_path / "pitching.db"}')

    from app import create_app
    from blueprints.fair_play import TeamPitchingSettings
    from db import db
    from models import Player, Team, TeamMembership, User

    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        db.create_all()
        db.session.add_all([
            Team(id=TEAM_ID, team_name='Truth', registration_code='truth', age_group='12U',
                 pitching_rule_set='MLB Pitch Smart', outfielder_count=3, timezone=TZ),
            User(id=1, username='coach', full_name='Test Coach',
                 password_hash=generate_password_hash('password123')),
        ])
        db.session.flush()
        db.session.add(TeamMembership(user_id=1, team_id=TEAM_ID, role='Head Coach', player_order=[]))
        db.session.add(TeamPitchingSettings(team_id=TEAM_ID, competition_default_rule='MLB Pitch Smart',
                                            arm_care_rule_set='MLB Pitch Smart'))
        for index, name in enumerate(NAMES, start=1):
            db.session.add(Player(id=index, team_id=TEAM_ID, name=name, number=str(index),
                                  pitcher_role='Starter'))
        db.session.commit()
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


def _client(app):
    client = app.test_client()
    with client.session_transaction() as session:
        session['logged_in'] = True
        session['username'] = 'coach'
        session['full_name'] = 'Test Coach'
        session['team_id'] = TEAM_ID
        session['role'] = 'Head Coach'
    return client


def _game(app, game_id, day, *, live=False, inning='1', pitcher_change=False, opponent='Visitors'):
    """A game on `day`. Started games have Graham relieve Hansen in the 2nd."""
    from db import db
    from models import Game, GameRotationEvent, Rotation

    with app.app_context():
        db.session.add(Game(id=game_id, team_id=TEAM_ID, date=datetime.combine(day, datetime.min.time()),
                            opponent=opponent, is_live=live, live_current_inning=inning))
        db.session.add(Rotation(title='Rotation', innings={'1': FIELD, '2': FIELD},
                                associated_game_id=game_id, team_id=TEAM_ID))
        if pitcher_change:
            db.session.add(GameRotationEvent(
                team_id=TEAM_ID, game_id=game_id, inning='2', sequence=1, event_type='Pitcher Change',
                before_alignment=FIELD, after_alignment=GRAHAM_P, pre_start=False))
        db.session.commit()


def _record(app, game_id, day, name, pitches):
    from db import db
    from models import PitchingOuting

    with app.app_context():
        db.session.add(PitchingOuting(date=datetime.combine(day, datetime.min.time()), opponent='Visitors',
                                      pitches=pitches, outing_type='Game', team_id=TEAM_ID,
                                      player_id=NAMES.index(name) + 1, game_id=game_id))
        db.session.commit()


def _placeholders(app, today, exclude=None):
    from db import db
    from models import PitchingOuting
    from unrecorded_pitching import unrecorded_game_outings

    with app.app_context():
        outings = db.session.query(PitchingOuting).all()
        return sorted(
            (o.player.name, o.game_id, o.pitching_now)
            for o in unrecorded_game_outings(TEAM_ID, outings, today, exclude_game_id=exclude)
        )


def test_a_live_game_has_its_pitchers_with_unknown_counts(app):
    _game(app, 7, TODAY, live=True, inning='2', pitcher_change=True)
    assert _placeholders(app, TODAY) == [('Graham', 7, True), ('Hansen', 7, False)]
    # The game being viewed shows its own pitching instead.
    assert _placeholders(app, TODAY, exclude=7) == []


def test_a_saved_count_or_an_unstarted_game_adds_nothing(app):
    _game(app, 7, TODAY, live=True, inning='2', pitcher_change=True)
    _record(app, 7, TODAY, 'Hansen', 0)          # a confirmed zero, entered
    assert _placeholders(app, TODAY) == [('Graham', 7, True)]
    _game(app, 8, TODAY + timedelta(days=1))      # scheduled, never started
    assert _placeholders(app, TODAY + timedelta(days=1)) == [('Graham', 7, True)]


def test_a_game_ended_without_counts_still_needs_them(app):
    _game(app, 7, TODAY - timedelta(days=1), live=False, inning='2', pitcher_change=True)
    assert _placeholders(app, TODAY) == [('Graham', 7, False), ('Hansen', 7, False)]
    # Finishing with counts saves a row per pitcher: nothing is missing.
    _record(app, 7, TODAY - timedelta(days=1), 'Hansen', 40)
    _record(app, 7, TODAY - timedelta(days=1), 'Graham', 12)
    assert _placeholders(app, TODAY) == []
    # Older than the look-back window: no longer affects eligibility.
    _game(app, 9, TODAY - timedelta(days=12), live=False, inning='2', pitcher_change=True)
    assert _placeholders(app, TODAY) == []


def _page(app):
    return _client(app).get('/pitching').get_data(as_text=True)


def _card(body, name):
    match = re.search(rf'<article class="cb-pitcher-card" data-player-name="{name}".*?</article>', body, re.S)
    assert match, name
    return match.group(0)


def test_the_pitching_page_says_pitching_now_and_count_needed(app):
    today = _local_today()
    _game(app, 7, today, live=True, inning='2', pitcher_change=True)
    body = _page(app)
    graham, hansen = _card(body, 'Graham'), _card(body, 'Hansen')
    assert 'data-badge-short="PITCHING"' in graham and 'Pitching Now' in graham
    assert 'data-badge-short="COUNT?"' in hansen and 'Pitched today — count needed.' in hansen
    for card in (graham, hansen):
        assert 'data-group="review"' in card
        assert 'Eligible Today' not in card
        assert '0 / 85' not in card                      # unknown, never zero
    assert 'id="pitchAllReady"' not in body


def test_throwing_history_shows_the_calendar_date(app):
    # Oct 1 at midnight was shown as "Wednesday, 09/30/26, 08:00 PM".
    _game(app, 7, date(2026, 10, 1))
    _record(app, 7, date(2026, 10, 1), 'Hansen', 58)
    body = _page(app)
    assert 'Thursday, 10/01/26' in body
    assert '09/30/26' not in body and '08:00 PM' not in body


def test_the_game_page_header_shows_the_calendar_date(app):
    _game(app, 7, date(2026, 10, 1))
    body = _client(app).get('/game/7').get_data(as_text=True)
    assert 'Thursday, 10/01/26' in body
    assert 'Wednesday, 09/30/26' not in body


def test_an_entered_count_shows_the_next_date_and_an_advisory_is_eligible(app):
    today = _local_today()
    _game(app, 7, today)
    _record(app, 7, today, 'Hansen', 58)
    hansen = _card(_page(app), 'Hansen')
    assert 'data-group="eligible"' in hansen and 'data-badge-short="ADVISORY"' in hansen
    expected = (today + timedelta(days=4)).strftime('%a, %b %d')
    assert f'Pitched today: 58 game pitches · 3 days rest needed — next available {expected}' in hansen


def test_the_scheduled_game_date_decides_pregame_eligibility(app):
    """The pregame picker reads this game's own state: its date, not today."""
    _game(app, 7, TODAY)
    _record(app, 7, TODAY, 'Hansen', 58)
    _game(app, 8, TODAY + timedelta(days=2), opponent='Tuesday')
    _game(app, 9, TODAY + timedelta(days=4), opponent='Monday')
    tuesday = _client(app).get('/api/live-game/8/state').get_json()['pitch_count_summary']['Hansen']
    monday = _client(app).get('/api/live-game/9/state').get_json()['pitch_count_summary']['Hansen']
    assert tuesday['eligibility'] == 'rule_conflict' and tuesday['next_available'] == 'Mon, Oct 05'
    assert monday['eligibility'] == 'ready'


def test_live_state_marks_this_games_pitchers(app):
    _game(app, 7, TODAY, live=True, inning='2', pitcher_change=True)
    summary = _client(app).get('/api/live-game/7/state').get_json()['pitch_count_summary']
    assert summary['Graham']['pitching_now'] is True
    assert summary['Hansen']['pitched_this_game'] is True and summary['Hansen']['pitching_now'] is False
    assert 'pitched_this_game' not in summary['Cole']
    # This game's own pitching does not make anyone "can't confirm".
    assert summary['Graham']['eligibility'] == 'ready'


# --- Edge cases ------------------------------------------------------------------------------

def _summary_for(app, game_id):
    return _client(app).get(f'/api/live-game/{game_id}/state').get_json()['pitch_count_summary']


def _marker_only_live_game(app, game_id, day, opponent='Visitors'):
    """Started by Start Game: only the 1st inning's 'Inning Started' marker."""
    from db import db
    from models import Game, GameRotationEvent, Rotation

    with app.app_context():
        db.session.add(Game(id=game_id, team_id=TEAM_ID, date=datetime.combine(day, datetime.min.time()),
                            opponent=opponent, is_live=True, live_current_inning='1'))
        db.session.add(Rotation(title='Rotation', innings={'1': FIELD, '2': FIELD},
                                associated_game_id=game_id, team_id=TEAM_ID))
        db.session.add(GameRotationEvent(
            team_id=TEAM_ID, game_id=game_id, inning='1', sequence=1, event_type='Inning Started',
            before_alignment=FIELD, after_alignment=FIELD, pre_start=False))
        db.session.commit()


def test_each_pitcher_is_checked_on_their_own(app):
    """A finished game with one count entered: the other pitcher still needs one."""
    _game(app, 7, TODAY - timedelta(days=1), live=False, inning='2', pitcher_change=True)
    _record(app, 7, TODAY - timedelta(days=1), 'Hansen', 40)
    assert _placeholders(app, TODAY) == [('Graham', 7, False)]


def test_a_confirmed_zero_and_a_missing_count_in_the_same_game(app):
    today = _local_today()
    _game(app, 7, today, live=False, inning='2', pitcher_change=True)
    _record(app, 7, today, 'Hansen', 0)                  # entered: zero
    body = _page(app)
    hansen, graham = _card(body, 'Hansen'), _card(body, 'Graham')
    assert 'data-group="eligible"' in hansen and 'data-workload-state' not in hansen
    assert '>0 / 85 pitches<' in hansen
    assert 'data-workload-state="count_needed"' in graham and 'Pitched today — count needed.' in graham


def test_the_starter_is_known_before_any_change(app):
    # Start Game's marker: Hansen is on the mound in the 1st, nothing else yet.
    _marker_only_live_game(app, 7, TODAY)
    assert _placeholders(app, TODAY) == [('Hansen', 7, True)]
    # A live game from before the marker existed: the plan says who started.
    from db import db
    from models import GameRotationEvent
    with app.app_context():
        db.session.query(GameRotationEvent).delete()
        db.session.commit()
    assert _placeholders(app, TODAY) == [('Hansen', 7, True)]


def test_a_removed_pitcher_is_still_known(app):
    _game(app, 7, TODAY, live=True, inning='3', pitcher_change=True)   # Hansen removed in the 2nd
    assert ('Hansen', 7, False) in _placeholders(app, TODAY)


def test_a_reopened_game_keeps_its_saved_counts(app):
    _game(app, 7, TODAY, live=True, inning='2', pitcher_change=True)   # reopened: live again
    _record(app, 7, TODAY, 'Hansen', 40)
    _record(app, 7, TODAY, 'Graham', 12)
    assert _placeholders(app, TODAY) == []
    summary = _summary_for(app, 7)
    assert summary['Hansen']['daily'] == 40 and 'pitched_this_game' not in summary['Hansen']
    assert summary['Graham']['daily'] == 12 and 'pitching_now' not in summary['Graham']


def test_counts_from_another_game_stay_visible(app):
    today = _local_today()
    _game(app, 6, today, opponent='Morning')
    _record(app, 6, today, 'Hansen', 30)                 # earlier game, entered
    _game(app, 7, today, live=True, inning='2', pitcher_change=True)
    hansen = _card(_page(app), 'Hansen')
    assert 'Pitched today — count needed. 30 game pitches already entered today.' in hansen
    assert '30+ / 85 pitches' in hansen and '30 entered; one count still needed' in hansen


def test_future_games_wait_only_as_long_as_a_count_could_matter(app):
    """Hansen is pitching now with no count. Pitch Smart 12U needs at most 4
    days of rest (85 pitches), so a game in 4 days can't be confirmed yet;
    a game in 5 days is not held up."""
    _marker_only_live_game(app, 7, TODAY)
    _game(app, 8, TODAY + timedelta(days=4), opponent='Soon')
    _game(app, 9, TODAY + timedelta(days=5), opponent='Later')
    soon, later = _summary_for(app, 8)['Hansen'], _summary_for(app, 9)['Hansen']
    assert soon['eligibility'] == 'unknown' and soon['status'].endswith('Pitch Count Incomplete')
    assert later['eligibility'] == 'ready'


def test_missing_workload_is_a_question_not_a_rule_violation(app):
    """Another live game today: Hansen can't be confirmed (review), and Start
    accepts the coach's "I verified" -- it is never a rule conflict."""
    _marker_only_live_game(app, 7, TODAY, opponent='Nitro')
    _game(app, 8, TODAY, opponent='Second Game')
    hansen = _summary_for(app, 8)['Hansen']
    assert hansen['eligibility'] == 'unknown' and hansen['eligibility'] != 'rule_conflict'
    assert hansen['status_detail'] == 'Pitching now vs Nitro. Enter the pitch count when the game ends.'

    start = f'/api/live-game/8/start'
    asked = _client(app).post(start, json={'inning_one': FIELD})
    assert asked.status_code == 409, asked.get_json()
    assert asked.get_json()['code'] == 'pitcher_eligibility_unconfirmed'
    question = asked.get_json()
    verified = _client(app).post(start, json={
        'inning_one': FIELD, 'pitching_decision': question['required_decision'],
        'pitching_decision_status': question['pitching_status'],
        'pitching_decision_rule_set': question['decision_rule_set'],
        'pitching_decision_reason': question['decision_reason']})
    assert verified.status_code == 200, verified.get_json()


def test_two_live_games_at_once(app):
    """Simultaneous live games: each sees the other's pitcher, not its own."""
    _marker_only_live_game(app, 7, TODAY, opponent='Field 1')
    _game(app, 8, TODAY, live=True, inning='2', pitcher_change=True, opponent='Field 2')
    in_first, in_second = _summary_for(app, 7), _summary_for(app, 8)
    # Game 7 (Hansen pitching): its own pitcher is ready to keep pitching;
    # Graham is pitching in game 8.
    assert in_first['Hansen']['pitching_now'] is True and in_first['Hansen']['eligibility'] == 'unknown'
    assert in_first['Graham']['status_detail'] == 'Pitching now vs Field 2. Enter the pitch count when the game ends.'
    # Game 8: Graham is its pitcher. Hansen pitched there and was removed,
    # so its re-entry rule decides -- not a count from another game.
    assert in_second['Graham']['pitching_now'] is True
    assert in_second['Hansen']['pitched_this_game'] is True
    assert in_second['Hansen']['eligibility'] == 'rule_conflict'
    assert 'removed from the mound' in in_second['Hansen']['eligibility_message']


def test_a_second_game_the_same_day_with_counts_entered(app):
    """Same-day multiple games: 30 entered from the first game is an
    advisory for the second (Pitch Smart), not a block."""
    today = _local_today()
    _game(app, 6, today, opponent='Morning')
    _record(app, 6, today, 'Hansen', 30)
    _game(app, 7, today, opponent='Evening')
    hansen = _summary_for(app, 7)['Hansen']
    assert hansen['eligibility'] == 'advisory' and hansen['daily'] == 30
    assert 'data-group="eligible"' in _card(_page(app), 'Hansen')


def test_one_lookup_per_request_and_no_query_per_player(app):
    """The started-game read happens once per request; later calls reuse it,
    and the cost does not grow with the number of pitchers or games."""
    from sqlalchemy import event as sa_event

    from db import db
    from models import PitchingOuting, Player
    from unrecorded_pitching import unrecorded_game_outings

    for game_id in (7, 8, 9):
        _game(app, game_id, TODAY - timedelta(days=game_id - 7), live=False, inning='2', pitcher_change=True)

    with app.test_request_context():
        outings = db.session.query(PitchingOuting).all()
        roster = db.session.query(Player).all()
        statements = []

        def capture(conn, cursor, statement, *args):
            statements.append(statement)

        sa_event.listen(db.engine, 'before_cursor_execute', capture)
        try:
            first = unrecorded_game_outings(TEAM_ID, outings, TODAY, roster=roster)
            again = unrecorded_game_outings(TEAM_ID, outings, TODAY, roster=roster)
            other_day = unrecorded_game_outings(TEAM_ID, outings, TODAY + timedelta(days=1), roster=roster)
        finally:
            sa_event.remove(db.engine, 'before_cursor_execute', capture)

    assert len(first) == 6 and len(again) == 6 and len(other_day) == 6   # 3 games x 2 pitchers
    # games once, then events and plans once for all three games -- no more.
    assert len(statements) == 3, statements
