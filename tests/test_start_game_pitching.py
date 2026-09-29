"""Start Game, Part 2: the starting pitcher.

After the 1st-inning defense checks (Part 1), Start evaluates the starter
with the same policy as every live pitching change (pitching_eligibility via
live_game_bulk_api._pitcher_eligibility), from fresh server state:

* Ready starts without a question;
* Advisory needs advisory_acknowledged, Rule conflict rule_override, Can't
  confirm eligibility_verified;
* no game pitching rules is not a hard stop: the starter can't be confirmed,
  and the coach may deliberately start without rules (no_rules_acknowledged),
  which never claims the pitcher is eligible.

A decision counts only for the exact status, rule set and reason the coach
saw, and never gets past a defense check. Accepted decisions are recorded
in the activity log as pitching_decision, naming Start Game (inning 1).

Real pitching histories produce each classification.
"""

from datetime import datetime, timedelta

import pytest

from test_start_game_contract import (  # noqa: F401 (app is a fixture)
    FULL,
    GAME_ID,
    START,
    _app,
    _client,
    _live,
    _plan,
    _start,
    _without,
)


GAME_DATE = datetime(2026, 10, 10, 10, 0, 0)
STARTER = 'Alex'


def _outing(app, days_before, *, pitches=None, innings=None, game_id=None, name=STARTER):
    from db import db
    from models import PitchingOuting, Player

    with app.app_context():
        player = db.session.query(Player).filter_by(name=name).one()
        db.session.add(PitchingOuting(
            player_id=player.id, team_id=1, date=GAME_DATE - timedelta(days=days_before),
            pitches=pitches, innings=innings, outing_type='Game', game_id=game_id,
            opponent='Earlier', pitcher_type='Starter',
        ))
        db.session.commit()


def _rules(app, competition):
    from blueprints.fair_play import TeamPitchingSettings
    from db import db

    with app.app_context():
        settings = db.session.query(TeamPitchingSettings).filter_by(team_id=1).one()
        settings.competition_default_rule = competition
        db.session.commit()


def _other_game_today(app):
    from db import db
    from models import Game

    with app.app_context():
        db.session.add(Game(id=41, team_id=1, date=GAME_DATE, opponent='Morning Game', is_live=False))
        db.session.commit()
    return 41


def _decision_log(app):
    from blueprints.security_guard import ActivityLog
    from db import db

    with app.app_context():
        return [row.detail for row in db.session.query(ActivityLog).filter_by(action='pitching_decision')]


def _answer(question):
    """The decision the browser sends back for the question it was shown."""
    return {
        'pitching_decision': question['required_decision'],
        'pitching_decision_status': question['pitching_status'],
        'pitching_decision_rule_set': question['decision_rule_set'],
        'pitching_decision_reason': question['decision_reason'],
    }


@pytest.fixture
def ready(app):
    _plan(app, {'1': FULL})
    return app


# --- Ready ------------------------------------------------------------------------------

def test_a_ready_starter_starts_without_a_question(ready):
    status, body = _start(ready, inning_one=FULL)
    assert status == 200, body
    assert _live(ready)
    assert _decision_log(ready) == []


# --- Advisory, Rule conflict, Can't confirm --------------------------------------------------

def test_an_advisory_starter_needs_an_acknowledgement(ready):
    # Pitch Smart recommends against pitching in a second game the same day.
    _rules(ready, 'MLB Pitch Smart')
    _outing(ready, 0, pitches=15, game_id=_other_game_today(ready))

    status, question = _start(ready, inning_one=FULL)
    assert status == 409, question
    assert question['code'] == 'pitcher_advisory'
    assert question['eligibility'] == 'advisory'
    assert question['required_decision'] == 'advisory_acknowledged'
    assert question['pitcher'] == STARTER
    assert question['eligibility_heading'] == 'Alex is eligible — please read this first'
    assert not _live(ready)

    status, body = _start(ready, inning_one=FULL, **_answer(question))
    assert status == 200, body
    assert _live(ready)


def test_a_rule_conflict_needs_the_override_decision(ready):
    # USSSA: more than 3 innings yesterday means rest today.
    _outing(ready, 1, innings=3.1)
    status, question = _start(ready, inning_one=FULL)
    assert status == 409, question
    assert question['code'] == 'pitcher_rule_conflict'
    assert question['required_decision'] == 'rule_override'
    assert question['rule_set'] == 'USSSA'
    assert question['eligibility_message'].startswith('USSSA: Resting.')
    assert 'intentionally overriding' in question['override_confirm']

    # Another decision type is not an override.
    wrong = dict(_answer(question), pitching_decision='advisory_acknowledged')
    status, again = _start(ready, inning_one=FULL, **wrong)
    assert status == 409 and again['code'] == 'pitcher_rule_conflict', again
    assert not _live(ready)

    status, body = _start(ready, inning_one=FULL, **_answer(question))
    assert status == 200, body


def test_cant_confirm_needs_i_verified(ready):
    _outing(ready, 1, innings=None)  # USSSA can't use a game with no innings
    status, question = _start(ready, inning_one=FULL)
    assert status == 409, question
    assert question['code'] == 'pitcher_eligibility_unconfirmed'
    assert question['required_decision'] == 'eligibility_verified'
    assert question['eligibility_heading'] == "CoachBoard can't confirm Alex's eligibility"

    status, body = _start(ready, inning_one=FULL, **_answer(question))
    assert status == 200, body


# --- No pitching rules ------------------------------------------------------------------------

def test_no_rules_asks_and_start_without_rules_records_cant_confirm(ready):
    _rules(ready, None)
    readiness = _client(ready).get(f'/api/game-day/{GAME_ID}/readiness').get_json()
    assert readiness['ready'] is True
    assert readiness['pitching_rules_selected'] is False
    assert readiness['hard_stops'] == []

    status, question = _start(ready, inning_one=FULL)
    assert status == 409, question
    assert question['code'] == 'start_no_pitching_rules'
    assert question['eligibility'] == 'unknown'
    assert question['eligibility_heading'] == "Pitching rules aren't selected"
    assert question['eligibility_message'] == (
        "CoachBoard can't confirm Alex's pitching eligibility without the game rules."
    )
    assert question['required_decision'] == 'no_rules_acknowledged'
    # "I verified" is not how a coach starts without rules.
    verified = dict(_answer(question), pitching_decision='eligibility_verified')
    status, again = _start(ready, inning_one=FULL, **verified)
    assert status == 409 and again['code'] == 'start_no_pitching_rules', again

    status, body = _start(ready, inning_one=FULL, **_answer(question))
    assert status == 200, body
    (entry,) = _decision_log(ready)
    assert entry.startswith(f'no_rules_acknowledged: game {GAME_ID}, Start Game (inning 1), pitcher Alex;')
    assert 'status Select Game Rules' in entry
    assert 'eligible' not in entry.split('shown:')[0]


# --- The decision is logged, and only for what the coach saw -----------------------------------

def test_an_accepted_decision_is_logged_with_rules_status_and_reason(ready):
    _outing(ready, 1, innings=3.1)
    _, question = _start(ready, inning_one=FULL)
    status, body = _start(ready, inning_one=FULL, **_answer(question))
    assert status == 200, body
    (entry,) = _decision_log(ready)
    assert entry == (
        f"rule_override: game {GAME_ID}, Start Game (inning 1), pitcher Alex; rules USSSA; "
        f"status Resting; shown: {question['eligibility_message']}"
    )


def test_a_decision_for_an_older_status_is_asked_again(ready):
    _outing(ready, 1, innings=None)
    _, question = _start(ready, inning_one=FULL)
    assert question['code'] == 'pitcher_eligibility_unconfirmed'

    # The missing innings are entered before Start: now a rule conflict.
    from db import db
    from models import PitchingOuting
    with ready.app_context():
        db.session.query(PitchingOuting).update({'innings': 3.1})
        db.session.commit()

    status, again = _start(ready, inning_one=FULL, **_answer(question))
    assert status == 409, again
    assert again['code'] == 'pitcher_rule_conflict'
    assert again['decision_outdated'] is True
    assert not _live(ready)
    assert _decision_log(ready) == []


def test_a_decision_for_a_different_reason_is_asked_again(ready):
    _outing(ready, 1, innings=3.1)
    _, question = _start(ready, inning_one=FULL)
    shown = dict(_answer(question), pitching_decision_reason='USSSA: Resting. Some other reason.')
    status, again = _start(ready, inning_one=FULL, **shown)
    assert status == 409 and again['decision_outdated'] is True, again
    assert not _live(ready)


# --- A decision never gets past a defense check ---------------------------------------------

def test_a_pitching_decision_never_bypasses_the_defense_checks(ready):
    _outing(ready, 1, innings=3.1)
    _, question = _start(ready, inning_one=FULL)
    decision = _answer(question)

    # Stale reviewed defense.
    _plan(ready, {'1': dict(FULL, SS='Jules', LF='Finn')})
    status, body = _start(ready, inning_one=FULL, **decision)
    assert status == 409 and body['code'] == 'start_defense_changed', body

    # Open position not acknowledged.
    _plan(ready, {'1': _without(FULL, 'CF')})
    status, body = _start(ready, inning_one=_without(FULL, 'CF'), **decision)
    assert status == 409 and body['code'] == 'start_open_positions', body

    # A player at two positions.
    _plan(ready, {'1': dict(FULL, SS='Alex')})
    status, body = _start(ready, inning_one=dict(FULL, SS='Alex'), **decision)
    assert status == 409 and body['code'] == 'start_hard_stops', body

    assert not _live(ready)
    assert _decision_log(ready) == []


def test_open_positions_are_asked_before_the_starter(ready):
    _outing(ready, 1, innings=3.1)
    plan = _without(FULL, 'CF')
    _plan(ready, {'1': plan})
    status, body = _start(ready, inning_one=plan)
    assert body['code'] == 'start_open_positions', body
    status, body = _start(ready, inning_one=plan, open_positions=['CF'])
    assert body['code'] == 'pitcher_rule_conflict', body
    status, body = _start(ready, inning_one=plan, open_positions=['CF'], **_answer(body))
    assert status == 200, body


def test_missing_p_is_still_a_hard_stop_even_without_rules(ready):
    _rules(ready, None)
    plan = _without(FULL, 'P')
    _plan(ready, {'1': plan})
    status, body = _start(ready, inning_one=plan, pitching_decision='no_rules_acknowledged')
    assert status == 409 and body['code'] == 'start_hard_stops', body
    assert 'Choose the starting pitcher for the 1st inning.' in body['hard_stops']
    assert not _live(ready)


# --- The game going live and the decision's record commit together --------------------------

@pytest.fixture
def commits(ready):
    """What each commit carried: (a game going live, a pitching-decision log)."""
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    from blueprints.security_guard import ActivityLog
    from models import Game

    seen = []

    def before_commit(session):
        live = any(isinstance(obj, Game) and obj.is_live for obj in session.dirty)
        logged = any(isinstance(obj, ActivityLog) and obj.action == 'pitching_decision'
                     for obj in session.new)
        if live or logged:
            seen.append((live, logged))

    event.listen(Session, 'before_commit', before_commit)
    yield seen
    event.remove(Session, 'before_commit', before_commit)


def test_a_rule_override_and_the_start_commit_together(ready, commits):
    _outing(ready, 1, innings=3.1)
    _, question = _start(ready, inning_one=FULL)
    status, body = _start(ready, inning_one=FULL, **_answer(question))
    assert status == 200, body
    assert commits == [(True, True)]
    assert _live(ready)
    assert len(_decision_log(ready)) == 1


def test_a_no_rules_acknowledgement_and_the_start_commit_together(ready, commits):
    _rules(ready, None)
    _, question = _start(ready, inning_one=FULL)
    status, body = _start(ready, inning_one=FULL, **_answer(question))
    assert status == 200, body
    assert commits == [(True, True)]
    (entry,) = _decision_log(ready)
    assert entry.startswith('no_rules_acknowledged:')


def test_a_ready_starter_commits_the_start_with_no_decision_log(ready, commits):
    status, body = _start(ready, inning_one=FULL)
    assert status == 200, body
    assert commits == [(True, False)]
    assert _decision_log(ready) == []


def test_if_the_decision_cannot_be_recorded_the_game_does_not_start(ready):
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    from blueprints.security_guard import ActivityLog

    _outing(ready, 1, innings=3.1)
    _, question = _start(ready, inning_one=FULL)

    def refuse_the_log(session, flush_context, instances):
        if any(isinstance(obj, ActivityLog) for obj in session.new):
            raise RuntimeError('activity log unavailable')

    event.listen(Session, 'before_flush', refuse_the_log)
    try:
        status, body = _start(ready, inning_one=FULL, **_answer(question))
    finally:
        event.remove(Session, 'before_flush', refuse_the_log)

    assert status == 500, body
    assert body['code'] == 'start_not_saved'
    assert not _live(ready)
    assert _decision_log(ready) == []

    # Nothing was left half-done: the same decision starts the game now.
    status, body = _start(ready, inning_one=FULL, **_answer(question))
    assert status == 200, body
    assert len(_decision_log(ready)) == 1


def test_if_the_record_cannot_even_be_built_the_game_does_not_start(ready, monkeypatch):
    from blueprints import live_game_bulk_api

    _outing(ready, 1, innings=3.1)
    _, question = _start(ready, inning_one=FULL)

    def broken(*args, **kwargs):
        raise RuntimeError('cannot build the log entry')

    monkeypatch.setattr(live_game_bulk_api, 'start_pitching_decision_row', broken)
    status, body = _start(ready, inning_one=FULL, **_answer(question))
    assert status == 500 and body['code'] == 'start_not_saved', body
    assert not _live(ready)
    assert _decision_log(ready) == []
