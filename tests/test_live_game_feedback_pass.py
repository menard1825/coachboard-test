from datetime import datetime

import pytest
from werkzeug.security import generate_password_hash


def _build_app(monkeypatch):
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')

    from app import create_app
    from db import db
    from models import Game, Player, Rotation, Team, TeamMembership, User

    app = create_app()
    app.config.update(TESTING=True)

    with app.app_context():
        db.create_all()
        team = Team(
            id=1,
            team_name='Real Game Feedback Team',
            registration_code='feedback-test-code',
            age_group='9U',
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

        names = ['Aiden', 'Bennett', 'Carter', 'Drew', 'Eli', 'Finn', 'Gavin', 'Hudson', 'Isaac', 'Jack']
        players = [Player(id=index + 1, name=name, number=str(index + 1), team_id=team.id) for index, name in enumerate(names)]
        db.session.add_all(players)

        inning_two = {
            'P': 'Aiden',
            'C': 'Bennett',
            '1B': 'Carter',
            '2B': 'Drew',
            '3B': 'Eli',
            'SS': 'Finn',
            'LF': 'Gavin',
            'CF': 'Hudson',
            'RF': 'Isaac',
        }
        inning_three = {
            'P': 'Aiden',
            'C': 'Bennett',
            '1B': 'Jack',
            '2B': 'Drew',
            '3B': 'Eli',
            'SS': 'Finn',
            'LF': 'Gavin',
            'CF': 'Hudson',
            'RF': 'Carter',
        }
        game = Game(
            id=70,
            date=datetime(2026, 8, 30, 17, 0, 0),
            opponent='Real Game Test',
            team_id=team.id,
            is_live=True,
            live_current_inning='2',
        )
        rotation = Rotation(
            id=1,
            title='Real Game Test Rotation',
            innings={'2': inning_two, '3': inning_three},
            associated_game_id=game.id,
            team_id=team.id,
        )
        db.session.add_all([game, rotation])
        db.session.commit()

    return app


def _login(client):
    with client.session_transaction() as session:
        session['logged_in'] = True
        session['username'] = 'coach'
        session['team_id'] = 1
        session['role'] = 'Head Coach'


def _inning_two_with_jack_in_right():
    return {
        'P': 'Aiden',
        'C': 'Bennett',
        '1B': 'Carter',
        '2B': 'Drew',
        '3B': 'Eli',
        'SS': 'Finn',
        'LF': 'Gavin',
        'CF': 'Hudson',
        'RF': 'Jack',
    }


def test_defense_edit_saves_one_event_and_returns_light_delta(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    response = client.post('/api/live-game/70/defense-edit', json={
        'base_sequence': 0,
        'alignment': _inning_two_with_jack_in_right(),
    })

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['status'] == 'success'
    assert 'delta' in payload
    assert 'state' not in payload
    assert payload['delta']['sequence'] == 1
    assert payload['delta']['current_inning'] == '2'
    assert payload['delta']['current_alignment']['RF'] == 'Jack'
    assert {player['name'] for player in payload['delta']['bench']} == {'Isaac'}

    from db import db
    from models import GameRotationEvent

    with app.app_context():
        events = db.session.query(GameRotationEvent).filter_by(game_id=70, team_id=1).all()
        assert len(events) == 1
        assert events[0].event_type == 'Bulk Defensive Change'
        assert events[0].before_alignment['RF'] == 'Isaac'
        assert events[0].after_alignment['RF'] == 'Jack'



def test_defense_edit_allows_open_non_pitcher_and_broadcasts_it(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    # Start with the exact live Inning 2 defense, then intentionally
    # send the shortstop to the bench without replacing the position.
    #
    # Live defense may have an OPEN non-pitcher position. That open
    # position must become authoritative so every connected coach sees
    # the same field.
    alignment = _inning_two_with_jack_in_right()
    alignment['RF'] = 'Isaac'
    alignment.pop('SS')

    response = client.post(
        '/api/live-game/70/defense-edit',
        json={
            'base_sequence': 0,
            'alignment': alignment,
        },
    )

    assert response.status_code == 200
    payload = response.get_json()

    assert payload['status'] == 'success'
    assert 'delta' in payload

    live_alignment = payload['delta']['current_alignment']

    assert live_alignment.get('P') == 'Aiden'
    assert 'SS' not in live_alignment
    assert live_alignment['RF'] == 'Isaac'

    bench_names = {
        player['name']
        for player in payload['delta']['bench']
    }

    assert {'Finn', 'Jack'}.issubset(bench_names)

    from db import db
    from models import GameRotationEvent

    with app.app_context():
        events = (
            db.session.query(GameRotationEvent)
            .filter_by(game_id=70, team_id=1)
            .all()
        )

        assert len(events) == 1
        assert events[0].event_type == 'Bulk Defensive Change'
        assert events[0].before_alignment['SS'] == 'Finn'
        assert 'SS' not in events[0].after_alignment
        assert events[0].after_alignment['P'] == 'Aiden'

def test_stale_second_coach_edit_is_rejected_without_overwriting_first(monkeypatch):
    app = _build_app(monkeypatch)
    first_client = app.test_client()
    second_client = app.test_client()
    _login(first_client)
    _login(second_client)

    first = first_client.post('/api/live-game/70/defense-edit', json={
        'base_sequence': 0,
        'alignment': _inning_two_with_jack_in_right(),
    })
    assert first.status_code == 200

    stale_attempt = {
        'P': 'Aiden',
        'C': 'Bennett',
        '1B': 'Carter',
        '2B': 'Drew',
        '3B': 'Eli',
        'SS': 'Finn',
        'LF': 'Gavin',
        'CF': 'Jack',
        'RF': 'Isaac',
    }
    second = second_client.post('/api/live-game/70/defense-edit', json={
        'base_sequence': 0,
        'alignment': stale_attempt,
    })

    assert second.status_code == 409
    payload = second.get_json()
    assert payload['code'] == 'stale_live_state'
    assert payload['current_sequence'] == 1
    assert payload['current_alignment']['RF'] == 'Jack'
    assert payload['current_alignment']['CF'] == 'Hudson'

    from blueprints.live_game_api import _actual_rotation
    from db import db
    from models import Game, GameRotationEvent

    with app.app_context():
        game = db.session.get(Game, 70)
        _, actual, _ = _actual_rotation(game, 1)
        assert actual['2']['RF'] == 'Jack'
        assert actual['2']['CF'] == 'Hudson'
        assert db.session.query(GameRotationEvent).filter_by(game_id=70, team_id=1).count() == 1


def test_advance_inning_commits_new_defense_and_inning_together(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    from blueprints.live_game_ui import GameNextInningPrep
    from db import db

    next_alignment = {
        'P': 'Aiden',
        'C': 'Bennett',
        '1B': 'Jack',
        '2B': 'Drew',
        '3B': 'Eli',
        'SS': 'Finn',
        'LF': 'Gavin',
        'CF': 'Hudson',
        'RF': 'Carter',
    }

    with app.app_context():
        db.session.add(GameNextInningPrep(
            inning='3',
            alignment=next_alignment,
            source='custom',
            updated_by='Test Coach',
            game_id=70,
            team_id=1,
        ))
        db.session.commit()

    response = client.post('/api/live-game/70/advance-inning', json={
        'base_sequence': 0,
        'alignment': next_alignment,
    })

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['status'] == 'success'
    assert payload['delta']['current_inning'] == '3'
    assert payload['delta']['current_alignment'] == next_alignment
    assert payload['delta']['event']['event_type'] == 'End Inning'
    assert payload['delta']['event']['inning'] == '3'

    from models import Game, GameRotationEvent

    with app.app_context():
        game = db.session.get(Game, 70)
        assert game.live_current_inning == '3'
        event = db.session.query(GameRotationEvent).filter_by(game_id=70, team_id=1).one()
        assert event.event_type == 'End Inning'
        assert event.inning == '3'
        assert event.after_alignment == next_alignment
        assert db.session.query(GameNextInningPrep).filter_by(game_id=70, team_id=1).first() is None


def _next_alignment_with_new_pitcher(pitcher_name):
    # Jack comes in from the bench to pitch; Aiden (the old pitcher) moves
    # to 1B instead of the bench, matching a realistic in-game shuffle.
    return {
        'P': pitcher_name,
        'C': 'Bennett',
        '1B': 'Aiden',
        '2B': 'Drew',
        '3B': 'Eli',
        'SS': 'Finn',
        'LF': 'Gavin',
        'CF': 'Hudson',
        'RF': 'Carter',
    }


def _seed_next_inning_prep(alignment):
    """Call inside an active app context."""
    from blueprints.live_game_ui import GameNextInningPrep
    from db import db

    db.session.add(GameNextInningPrep(
        inning='3',
        alignment=alignment,
        source='custom',
        updated_by='Test Coach',
        game_id=70,
        team_id=1,
    ))
    db.session.commit()


def test_advance_inning_eligible_new_pitcher_succeeds(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    from blueprints import live_game_bulk_api as bulk_module
    monkeypatch.setattr(
        bulk_module,
        'get_authoritative_live_state',
        lambda game_id, team_id: {'pitch_count_summary': {'Jack': {'status': 'Available'}}},
    )

    next_alignment = _next_alignment_with_new_pitcher('Jack')

    with app.app_context():
        _seed_next_inning_prep(next_alignment)

    response = client.post('/api/live-game/70/advance-inning', json={
        'base_sequence': 0,
        'alignment': next_alignment,
    })

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['status'] == 'success'
    assert payload['delta']['current_inning'] == '3'
    assert payload['delta']['current_alignment']['P'] == 'Jack'

    from blueprints.live_game_ui import GameNextInningPrep
    from db import db
    from models import Game

    with app.app_context():
        game = db.session.get(Game, 70)
        assert game.live_current_inning == '3'
        assert db.session.query(GameNextInningPrep).filter_by(game_id=70, team_id=1).first() is None


def test_advance_inning_continuing_pitcher_bypasses_eligibility_gate(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    # Aiden continues from NOW into NEXT. If the gate were invoked at all
    # for a continuing pitcher, this would raise and fail the test.
    from blueprints import live_game_bulk_api as bulk_module

    def _boom(game_id, team_id):
        raise AssertionError(
            'the new-pitcher eligibility gate must not run for a '
            'continuing pitcher'
        )
    monkeypatch.setattr(bulk_module, 'get_authoritative_live_state', _boom)

    next_alignment = {
        'P': 'Aiden',
        'C': 'Bennett',
        '1B': 'Jack',
        '2B': 'Drew',
        '3B': 'Eli',
        'SS': 'Finn',
        'LF': 'Gavin',
        'CF': 'Hudson',
        'RF': 'Carter',
    }

    with app.app_context():
        _seed_next_inning_prep(next_alignment)

    response = client.post('/api/live-game/70/advance-inning', json={
        'base_sequence': 0,
        'alignment': next_alignment,
    })

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['status'] == 'success'
    assert payload['delta']['current_alignment']['P'] == 'Aiden'


RULE_CONFLICT = 'pitcher_rule_conflict'
UNCONFIRMED = 'pitcher_eligibility_unconfirmed'


@pytest.mark.parametrize('pitch_count_summary, expected_code, expected_message_fragment', [
    ({'Jack': {'status': 'Resting', 'status_detail': '40 game pitches on Mon, Aug 24 require 2 day(s) rest.'}},
     RULE_CONFLICT, ': Resting. 40 game pitches on Mon, Aug 24 require 2 day(s) rest.'),
    ({'Jack': {'status': 'Unavailable — Same-Day Game Restriction'}},
     RULE_CONFLICT, ': Same-Day Game Restriction.'),
    ({'Jack': {'status': 'Ineligible', 'status_detail': 'One-day or rolling three-day innings limit reached.'}},
     RULE_CONFLICT, 'innings limit reached'),
    ({'Jack': {'status': 'Pitch Count Incomplete'}}, UNCONFIRMED, 'Pitch Count Incomplete'),
    ({'Jack': {'status': 'Unavailable — Innings Incomplete'}}, UNCONFIRMED, 'Innings Incomplete'),
    ({'Jack': {'status': 'Verify Rules'}}, UNCONFIRMED, 'Verify Rules'),
    ({'Jack': {'status': 'Unavailable — Select Game Rules'}}, UNCONFIRMED, 'Select Game Rules'),
    ({'Jack': {'status': 'Eligibility Error', 'status_detail': "CoachBoard could not calculate pitching eligibility."}},
     UNCONFIRMED, 'Eligibility Error'),
    ({}, UNCONFIRMED, "CoachBoard can't confirm Jack's pitching eligibility."),
    ({'Jack': {'status': ''}}, UNCONFIRMED, "CoachBoard can't confirm Jack's pitching eligibility."),
    ({'Jack': {'status': 'Something Nobody Has Invented Yet'}},
     RULE_CONFLICT, 'Something Nobody Has Invented Yet'),
], ids=[
    'resting', 'same_day_game', 'innings_limit', 'pitch_count_incomplete',
    'innings_incomplete', 'verify_rules', 'rules_not_selected', 'eligibility_error',
    'missing_summary', 'empty_status', 'unknown_future_status',
])
def test_advance_inning_flagged_new_pitcher_needs_a_decision(
    monkeypatch, pitch_count_summary, expected_code, expected_message_fragment
):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    from blueprints import live_game_bulk_api as bulk_module
    monkeypatch.setattr(
        bulk_module,
        'get_authoritative_live_state',
        lambda game_id, team_id: {'pitch_count_summary': pitch_count_summary},
    )

    next_alignment = _next_alignment_with_new_pitcher('Jack')

    with app.app_context():
        _seed_next_inning_prep(next_alignment)

    response = client.post('/api/live-game/70/advance-inning', json={
        'base_sequence': 0,
        'alignment': next_alignment,
    })

    assert response.status_code == 409
    payload = response.get_json()
    assert payload['status'] == 'error'
    assert payload['code'] == expected_code
    assert expected_message_fragment in payload['message']
    if expected_code == UNCONFIRMED:
        assert "can't confirm" in payload['message']
        assert payload['required_decision'] == 'eligibility_verified'
    else:
        assert "can't confirm" not in payload['message']
        assert payload['required_decision'] == 'rule_override'
        assert payload['eligibility_heading'] == 'Jack appears ineligible to pitch'
        assert payload['override_confirm'].startswith(
            'CoachBoard believes this may violate the selected'
        )

    from blueprints.live_game_ui import GameNextInningPrep
    from db import db
    from models import Game, GameRotationEvent

    with app.app_context():
        game = db.session.get(Game, 70)
        assert game.live_current_inning == '2'
        assert db.session.query(GameNextInningPrep).filter_by(game_id=70, team_id=1).first() is not None
        assert db.session.query(GameRotationEvent).filter_by(game_id=70, team_id=1).count() == 0


@pytest.mark.parametrize('pitch_count_summary, expected_message_fragment', [
    ({'Carter': {'status': 'Eligibility Error'}}, 'Eligibility Error'),
    ({}, "CoachBoard can't confirm Carter's pitching eligibility."),
    ({'Carter': {'status': 'Something Nobody Has Invented Yet'}}, 'Something Nobody Has Invented Yet'),
], ids=['eligibility_error', 'missing_summary', 'unknown_future_status'])
def test_complete_pitcher_change_blocks_via_shared_helper(monkeypatch, pitch_count_summary, expected_message_fragment):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    from blueprints import live_game_bulk_api as bulk_module
    monkeypatch.setattr(
        bulk_module,
        'get_authoritative_live_state',
        lambda game_id, team_id: {'pitch_count_summary': pitch_count_summary},
    )

    swapped = {
        'P': 'Carter',
        'C': 'Bennett',
        '1B': 'Aiden',
        '2B': 'Drew',
        '3B': 'Eli',
        'SS': 'Finn',
        'LF': 'Gavin',
        'CF': 'Hudson',
        'RF': 'Isaac',
    }
    response = client.post('/api/live-game/70/complete-pitcher-change', json={
        'base_sequence': 0,
        'fast': True,
        'new_pitcher_id': 3,
        'alignment': swapped,
    })

    assert response.status_code == 409
    payload = response.get_json()
    assert payload['status'] == 'error'
    assert expected_message_fragment in payload['message']

    from models import Game, GameRotationEvent
    from db import db

    with app.app_context():
        game = db.session.get(Game, 70)
        assert game.live_current_inning == '2'
        assert db.session.query(GameRotationEvent).filter_by(game_id=70, team_id=1).count() == 0



def _patch_summary(monkeypatch, summary):
    from blueprints import live_game_bulk_api as bulk_module

    monkeypatch.setattr(
        bulk_module,
        'get_authoritative_live_state',
        lambda game_id, team_id: {'pitch_count_summary': summary},
    )


CARTER_TO_P = {
    # Carter moves from 1B to P; the outgoing pitcher sits and 1B stays open.
    'P': 'Carter', 'C': 'Bennett', '2B': 'Drew', '3B': 'Eli',
    'SS': 'Finn', 'LF': 'Gavin', 'CF': 'Hudson', 'RF': 'Isaac',
}


def _change_to_carter(client, **flags):
    return client.post('/api/live-game/70/complete-pitcher-change', json={
        'base_sequence': 0,
        'fast': True,
        'new_pitcher_id': 3,
        'alignment': CARTER_TO_P,
        **flags,
    })


def _event_count(app):
    from db import db
    from models import GameRotationEvent

    with app.app_context():
        return db.session.query(GameRotationEvent).filter_by(game_id=70, team_id=1).count()


CARTER_RESTING = {
    'Carter': {
        'status': 'Resting',
        'daily': 0,
        'status_detail': '66 game pitches on Sun, Sep 27 require 3 day(s) rest.',
    },
}


@pytest.mark.parametrize('flags', [
    {},
    # The old generic flag says nothing about which warning was seen.
    {'pitch_anyway': True},
    # A lighter decision than the rule needs.
    {'pitching_decision': 'eligibility_verified', 'pitching_decision_status': 'Resting'},
    {'pitching_decision': 'advisory_acknowledged', 'pitching_decision_status': 'Resting'},
], ids=['no_decision', 'legacy_pitch_anyway', 'verification', 'advisory_ack'])
def test_required_rest_is_a_rule_conflict_needing_an_override(monkeypatch, flags):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)
    _patch_summary(monkeypatch, CARTER_RESTING)

    response = _change_to_carter(client, **flags)

    assert response.status_code == 409
    payload = response.get_json()
    assert payload['code'] == 'pitcher_rule_conflict'
    assert payload['eligibility'] == 'rule_conflict'
    assert payload['required_decision'] == 'rule_override'
    assert payload['pitching_status'] == 'Resting'
    assert payload['eligibility_heading'] == 'Carter appears ineligible to pitch'
    assert payload['eligibility_message'].endswith(
        ': Resting. 66 game pitches on Sun, Sep 27 require 3 day(s) rest.'
    )
    if flags.get('pitch_anyway'):
        assert payload['message'].endswith('Refresh CoachBoard to decide on this warning.')
    assert _event_count(app) == 0
    assert _decision_log(app) == []


def test_coach_can_explicitly_override_required_rest(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)
    _patch_summary(monkeypatch, CARTER_RESTING)

    response = _change_to_carter(
        client, pitching_decision='rule_override', pitching_decision_status='Resting'
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()['delta']['current_alignment']['P'] == 'Carter'
    assert _event_count(app) == 1
    (detail,) = _decision_log(app)
    assert detail.startswith('rule_override: game 70, Pitcher Change')
    assert 'pitcher Carter;' in detail
    assert 'status Resting;' in detail
    assert '66 game pitches on Sun, Sep 27 require 3 day(s) rest.' in detail


def test_override_for_a_status_that_changed_is_asked_again(monkeypatch):
    """A decision covers the warning the coach saw, not whatever is true now."""
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)
    _patch_summary(monkeypatch, {
        'Carter': {'status': 'Already Pitched This Game', 'status_detail': 'Carter already pitched.'},
    })

    response = _change_to_carter(
        client, pitching_decision='rule_override', pitching_decision_status='Resting'
    )

    assert response.status_code == 409
    payload = response.get_json()
    assert payload['decision_outdated'] is True
    assert payload['pitching_status'] == 'Already Pitched This Game'
    assert _event_count(app) == 0


@pytest.mark.parametrize('route', ['complete-pitcher-change', 'advance-inning'])
def test_override_never_bypasses_the_stale_field_check(monkeypatch, route):
    """A rule override is a coach decision; a changed field is a software
    stop. The version check still refuses the write."""
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)
    _patch_summary(monkeypatch, {**CARTER_RESTING, 'Jack': {'status': 'Resting'}})

    decision = {'pitching_decision': 'rule_override', 'pitching_decision_status': 'Resting'}
    if route == 'complete-pitcher-change':
        response = _change_to_carter(client, **{**decision, 'base_sequence': 7})
    else:
        next_alignment = _next_alignment_with_new_pitcher('Jack')
        with app.app_context():
            _seed_next_inning_prep(next_alignment)
        response = client.post('/api/live-game/70/advance-inning', json={
            'base_sequence': 7, 'alignment': next_alignment, **decision,
        })

    assert response.status_code == 409
    assert response.get_json()['code'] == 'stale_live_state'
    assert _event_count(app) == 0
    assert _decision_log(app) == []


def test_complete_pitcher_change_unknown_needs_explicit_verification(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)
    _patch_summary(monkeypatch, {
        'Carter': {
            'status': 'Unavailable — Pitch Count Incomplete',
            'status_detail': 'Verify missing game pitch counts before using this pitcher.',
        },
    })

    refused = _change_to_carter(client)
    assert refused.status_code == 409
    assert refused.get_json()['code'] == 'pitcher_eligibility_unconfirmed'
    assert refused.get_json()['message'].startswith(
        "CoachBoard can't confirm Carter's pitching eligibility (Pitch Count Incomplete)."
    )
    assert refused.get_json()['required_decision'] == 'eligibility_verified'
    assert _event_count(app) == 0

    # Verification is its own decision; a rule override does not stand in.
    wrong = _change_to_carter(
        client,
        pitching_decision='rule_override',
        pitching_decision_status='Unavailable — Pitch Count Incomplete',
    )
    assert wrong.status_code == 409
    assert _event_count(app) == 0

    confirmed = _change_to_carter(
        client,
        pitching_decision='eligibility_verified',
        pitching_decision_status='Unavailable — Pitch Count Incomplete',
    )
    assert confirmed.status_code == 200
    payload = confirmed.get_json()
    assert payload['delta']['current_alignment']['P'] == 'Carter'
    assert payload['delta']['event']['event_type'] == 'Pitcher Change'
    assert _event_count(app) == 1


def test_advance_inning_unknown_needs_explicit_verification(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)
    _patch_summary(monkeypatch, {'Jack': {'status': 'Unavailable — Innings Incomplete'}})

    next_alignment = _next_alignment_with_new_pitcher('Jack')
    with app.app_context():
        _seed_next_inning_prep(next_alignment)

    body = {'base_sequence': 0, 'alignment': next_alignment}
    refused = client.post('/api/live-game/70/advance-inning', json=body)
    assert refused.status_code == 409
    assert refused.get_json()['code'] == 'pitcher_eligibility_unconfirmed'

    confirmed = client.post(
        '/api/live-game/70/advance-inning',
        json={
            **body,
            'pitching_decision': 'eligibility_verified',
            'pitching_decision_status': 'Unavailable — Innings Incomplete',
        },
    )
    assert confirmed.status_code == 200
    assert confirmed.get_json()['delta']['current_alignment']['P'] == 'Jack'
    (detail,) = _decision_log(app)
    assert detail.startswith('eligibility_verified: game 70, End Inning')


@pytest.mark.parametrize('status, detail', [
    ('Resting', '66 game pitches on Sun, Sep 27 require 3 day(s) rest.'),
    ('Ineligible', 'One-day or rolling three-day innings limit reached.'),
    ('Already Pitched This Game', 'Jack already pitched and was removed from the mound.'),
], ids=['required_rest', 'innings_limit', 'reentry'])
def test_end_inning_rule_conflict_needs_an_explicit_override(monkeypatch, status, detail):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)
    _patch_summary(monkeypatch, {'Jack': {'status': status, 'status_detail': detail}})

    next_alignment = _next_alignment_with_new_pitcher('Jack')
    with app.app_context():
        _seed_next_inning_prep(next_alignment)
    body = {'base_sequence': 0, 'alignment': next_alignment}

    for not_enough in (
        {},
        {'pitch_anyway': True},
        {'pitching_decision': 'eligibility_verified', 'pitching_decision_status': status},
    ):
        refused = client.post('/api/live-game/70/advance-inning', json={**body, **not_enough})
        assert refused.status_code == 409
        assert refused.get_json()['code'] == 'pitcher_rule_conflict'
        assert refused.get_json()['required_decision'] == 'rule_override'
        assert detail in refused.get_json()['eligibility_message']
    assert _event_count(app) == 0

    overridden = client.post('/api/live-game/70/advance-inning', json={
        **body, 'pitching_decision': 'rule_override', 'pitching_decision_status': status,
    })
    assert overridden.status_code == 200, overridden.get_json()
    assert overridden.get_json()['delta']['current_alignment']['P'] == 'Jack'
    (logged,) = _decision_log(app)
    assert logged.startswith('rule_override: game 70, End Inning')
    assert f'status {status};' in logged


def test_field_player_can_take_mound_without_benching_outgoing_pitcher(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    # This test is about the defensive swap behavior. Keep pitching eligibility
    # deterministic here; the fail-closed eligibility rules have their own tests.
    from blueprints import live_game_bulk_api as bulk_module
    monkeypatch.setattr(
        bulk_module,
        'get_authoritative_live_state',
        lambda game_id, team_id: {'pitch_count_summary': {'Carter': {'status': 'Available'}}},
    )

    # Carter was at 1B. The common youth-baseball swap is Carter -> P and the
    # old pitcher Aiden -> 1B, with nobody unnecessarily sent to the bench.
    swapped = {
        'P': 'Carter',
        'C': 'Bennett',
        '1B': 'Aiden',
        '2B': 'Drew',
        '3B': 'Eli',
        'SS': 'Finn',
        'LF': 'Gavin',
        'CF': 'Hudson',
        'RF': 'Isaac',
    }
    response = client.post('/api/live-game/70/complete-pitcher-change', json={
        'base_sequence': 0,
        'fast': True,
        'new_pitcher_id': 3,
        'alignment': swapped,
    })

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['delta']['current_alignment']['P'] == 'Carter'
    assert payload['delta']['current_alignment']['1B'] == 'Aiden'
    assert {player['name'] for player in payload['delta']['bench']} == {'Jack'}
    assert payload['delta']['event']['event_type'] == 'Pitcher Change'


def test_quick_field_rejects_player_marked_out(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    from db import db
    from models import GameRotationEvent, PlayerGameAbsence

    # Jack is player 10 in this fixture and begins on the bench.
    # Mark him Out, then reproduce the Quick Field request that would
    # otherwise put him into RF.
    with app.app_context():
        db.session.add(PlayerGameAbsence(
            player_id=10,
            game_id=70,
            team_id=1,
        ))
        db.session.commit()

    response = client.post('/api/live-game/70/defensive-change', json={
        'player_id': 10,
        'destination_position': 'RF',
        'base_sequence': 0,
    })

    assert response.status_code == 409
    payload = response.get_json()
    assert payload['status'] == 'error'
    assert 'not available for this game' in payload['message']

    with app.app_context():
        assert db.session.query(GameRotationEvent).filter_by(
            game_id=70,
            team_id=1,
        ).count() == 0



def test_weekend_multicoach_write_guards(monkeypatch):
    app = _build_app(monkeypatch)
    first_client = app.test_client()
    second_client = app.test_client()
    _login(first_client)
    _login(second_client)

    from db import db
    from models import (
        GameRotationEvent,
        Player,
        PlayerGameAbsence,
    )

    # Old/unversioned Quick Field requests fail closed.
    response = first_client.post(
        '/api/live-game/70/defensive-change',
        json={
            'player_id': 10,
            'destination_position': 'RF',
        },
    )
    assert response.status_code == 409
    assert (
        response.get_json()['code']
        == 'missing_live_state_version'
    )

    # Coach 1 saves from sequence 0.
    response = first_client.post(
        '/api/live-game/70/defensive-change',
        json={
            'player_id': 10,
            'destination_position': 'RF',
            'base_sequence': 0,
        },
    )
    assert response.status_code == 200

    with app.app_context():
        assert db.session.query(
            GameRotationEvent
        ).filter_by(
            game_id=70,
            team_id=1,
        ).count() == 1

    # Coach 2 is still looking at sequence 0.
    # Their otherwise-valid move must not overwrite Coach 1.
    response = second_client.post(
        '/api/live-game/70/defensive-change',
        json={
            'player_id': 10,
            'destination_position': 'CF',
            'base_sequence': 0,
        },
    )
    assert response.status_code == 409

    payload = response.get_json()
    assert payload['code'] == 'stale_live_state'
    assert payload['current_sequence'] == 1
    assert payload['current_alignment']['RF'] == 'Jack'

    # Bulk/chained Quick Field cannot bypass version checking.
    alignment = {
        'P': 'Aiden',
        'C': 'Bennett',
        '1B': 'Carter',
        '2B': 'Drew',
        '3B': 'Eli',
        'SS': 'Finn',
        'LF': 'Gavin',
        'CF': 'Hudson',
        'RF': 'Isaac',
    }

    response = first_client.post(
        '/api/live-game/70/set-defense',
        json={'alignment': alignment},
    )
    assert response.status_code == 409
    assert (
        response.get_json()['code']
        == 'missing_live_state_version'
    )

    # Undo also requires the state version.
    response = first_client.post(
        '/api/live-game/70/undo',
        json={},
    )
    assert response.status_code == 409
    assert (
        response.get_json()['code']
        == 'missing_live_state_version'
    )

    # The old direct inning-advance route is shut down.
    response = first_client.post(
        '/api/live-game/70/end-inning',
        json={},
    )
    assert response.status_code == 409
    assert (
        response.get_json()['code']
        == 'legacy_live_write_disabled'
    )

    # Playing / Out cannot change once first pitch happened.
    response = first_client.post(
        '/game/70/update_absences',
        data={'absent_players': '10'},
    )
    assert response.status_code == 302

    with app.app_context():
        assert db.session.query(
            PlayerGameAbsence
        ).filter_by(
            game_id=70,
            team_id=1,
            player_id=10,
        ).count() == 0

    # Guest-status changes are locked once the game is live.
    #
    # Keep Jack's name unchanged here. A rename is already independently
    # protected by CoachBoard's historical-player safety guard because Jack
    # appears in the saved rotation fixture. This request specifically tests
    # the new live-roster lock.
    response = first_client.post(
        '/update_player_inline/10',
        data={
            'name': 'Jack',
            'roster_status': 'guest',
        },
    )
    assert response.status_code == 409

    payload = response.get_json()
    assert payload['code'] == 'live_roster_locked'

    with app.app_context():
        player = db.session.get(Player, 10)
        assert player.name == 'Jack'
        assert player.is_guest is False


def test_invalid_live_alignment_stays_visible(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    from db import db
    from models import Rotation

    with app.app_context():
        rotation = db.session.get(Rotation, 1)
        innings = dict(rotation.innings or {})
        inning_two = dict(innings['2'])
        inning_two['RF'] = 'Renamed Player'
        innings['2'] = inning_two
        rotation.innings = innings
        db.session.commit()

    response = client.get('/api/live-game/70/state')
    assert response.status_code == 200

    payload = response.get_json()

    assert (
        payload['current_alignment']['RF']
        == 'Renamed Player'
    )
    assert payload['current_alignment'] != {}
    assert payload['alignment_valid'] is False
    assert (
        'Renamed Player'
        in payload['alignment_offending_names']
    )


def test_reverted_event_does_not_count_as_active_version(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    from db import db
    from models import GameRotationEvent

    inning_two = {
        'P': 'Aiden',
        'C': 'Bennett',
        '1B': 'Carter',
        '2B': 'Drew',
        '3B': 'Eli',
        'SS': 'Finn',
        'LF': 'Gavin',
        'CF': 'Hudson',
        'RF': 'Isaac',
    }

    with app.app_context():
        db.session.add(
            GameRotationEvent(
                team_id=1,
                game_id=70,
                inning='2',
                sequence=1,
                event_type='Defensive Change',
                changed_by_user='coach',
                before_alignment=inning_two,
                after_alignment=inning_two,
                reverted=True,
            )
        )
        db.session.commit()

    response = client.post(
        '/api/live-game/70/defense-edit',
        json={
            'base_sequence': 0,
            'alignment': _inning_two_with_jack_in_right(),
        },
    )

    assert response.status_code == 200
    payload = response.get_json()

    assert payload['delta']['sequence'] == 2


def test_verified_unknown_eligibility_is_recorded(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)
    _patch_summary(monkeypatch, {'Carter': {'status': 'Unavailable — Pitch Count Incomplete'}})

    assert _decision_log(app) == []
    response = _change_to_carter(
        client,
        pitching_decision='eligibility_verified',
        pitching_decision_status='Unavailable — Pitch Count Incomplete',
    )
    assert response.status_code == 200

    event_id = response.get_json()['delta']['event']['id']
    (row,) = _decision_rows(app)
    assert row['detail'].startswith(
        f'eligibility_verified: game 70, Pitcher Change (event {event_id}, '
        'inning 2), pitcher Carter; rules '
    )
    assert row['detail'].endswith(
        "status Pitch Count Incomplete; shown: CoachBoard can't confirm "
        "Carter's pitching eligibility (Pitch Count Incomplete)."
    )
    # Who and when come from the activity log itself.
    assert row['user_id'] is not None
    assert row['created_at'] is not None


def test_ready_pitcher_records_no_decision(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)
    _patch_summary(monkeypatch, {'Carter': {'status': 'Available'}})

    assert _change_to_carter(
        client, pitching_decision='rule_override', pitching_decision_status='Available'
    ).status_code == 200
    assert _decision_log(app) == []


def test_advisory_needs_only_an_acknowledgement(monkeypatch):
    """Pitch Smart's same-day recommendation: shown, then Continue."""
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)
    _patch_summary(monkeypatch, {
        'Carter': {'status': 'Same-Day Game Advisory', 'advisory': True},
        'Jack': {'status': 'Same-Day Game Advisory', 'advisory': True},
    })

    shown = _change_to_carter(client)
    assert shown.status_code == 409
    assert shown.get_json()['code'] == 'pitcher_advisory'
    assert shown.get_json()['required_decision'] == 'advisory_acknowledged'
    assert 'override_confirm' not in shown.get_json()

    ack = {
        'pitching_decision': 'advisory_acknowledged',
        'pitching_decision_status': 'Same-Day Game Advisory',
    }
    assert _change_to_carter(client, **ack).status_code == 200

    next_alignment = _next_alignment_with_new_pitcher('Jack')
    with app.app_context():
        _seed_next_inning_prep(next_alignment)
    response = client.post('/api/live-game/70/advance-inning', json={
        'base_sequence': 1,
        'alignment': next_alignment,
        **ack,
    })
    assert response.status_code == 200, response.get_json()
    assert [d.split(':')[0] for d in _decision_log(app)] == [
        'advisory_acknowledged', 'advisory_acknowledged',
    ]


@pytest.mark.parametrize('flags, allowed', [
    ({'pitch_anyway': True}, False),
    ({'pitching_decision': 'eligibility_verified',
      'pitching_decision_status': 'Already Pitched This Game'}, False),
    ({'pitching_decision': 'rule_override',
      'pitching_decision_status': 'Already Pitched This Game'}, True),
], ids=['legacy_pitch_anyway', 'verification', 'rule_override'])
def test_reentry_is_overridable_only_explicitly(monkeypatch, flags, allowed):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)
    reason = (
        'Carter already pitched and was removed from the mound. USSSA rules '
        'indicate Carter cannot return to pitch in this game.'
    )
    _patch_summary(monkeypatch, {
        'Carter': {'status': 'Already Pitched This Game', 'status_detail': reason},
    })

    response = _change_to_carter(client, **flags)
    if not allowed:
        assert response.status_code == 409
        payload = response.get_json()
        assert payload['code'] == 'pitcher_rule_conflict'
        assert payload['eligibility_message'] == reason
        assert _event_count(app) == 0
        return

    assert response.status_code == 200
    assert _event_count(app) == 1
    (detail,) = _decision_log(app)
    assert detail.startswith('rule_override:')
    assert reason in detail


def _decision_rows(app):
    from blueprints.security_guard import ActivityLog
    from db import db

    with app.app_context():
        return [
            {'detail': row.detail, 'user_id': row.user_id, 'created_at': row.created_at}
            for row in db.session.query(ActivityLog)
            .filter_by(action='pitching_decision')
            .order_by(ActivityLog.id)
            .all()
        ]


def _decision_log(app):
    return [row['detail'] for row in _decision_rows(app)]


# ------------------------------------------- a coach-resolved defensive chain

INNING_TWO = {
    'P': 'Aiden', 'C': 'Bennett', '1B': 'Carter', '2B': 'Drew', '3B': 'Eli',
    'SS': 'Finn', 'LF': 'Gavin', 'CF': 'Hudson', 'RF': 'Isaac',
}


def test_a_resolved_defensive_chain_is_one_pitching_change_and_one_undo(monkeypatch):
    """Jack (bench) pitches; the coach sends Aiden to 1B, Carter from 1B to
    LF and Gavin from LF to the bench. The whole decision is one event."""
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)
    _patch_summary(monkeypatch, {'Jack': {'status': 'Available'}})

    after = dict(INNING_TWO, P='Jack', **{'1B': 'Aiden', 'LF': 'Carter'})
    response = client.post('/api/live-game/70/complete-pitcher-change', json={
        'base_sequence': 0, 'fast': True, 'new_pitcher_id': 10, 'alignment': after,
    })
    assert response.status_code == 200, response.get_json()
    assert response.get_json()['delta']['current_alignment'] == after
    assert _event_count(app) == 1

    from db import db
    from models import GameRotationEvent

    with app.app_context():
        (event,) = db.session.query(GameRotationEvent).filter_by(game_id=70).all()
        assert event.event_type == 'Pitcher Change'
        assert event.before_alignment == INNING_TWO
        assert event.after_alignment == after

    undone = client.post('/api/live-game/70/undo', json={'base_sequence': 1})
    assert undone.status_code == 200

    from blueprints.live_game_api import _actual_rotation
    from models import Game

    with app.app_context():
        (event,) = db.session.query(GameRotationEvent).filter_by(game_id=70).all()
        assert event.reverted is True
        # The one Undo restores the whole field, pitcher included. (This
        # fixture starts at inning 2 without End Inning events, so read
        # inning 2's field directly.)
        _, actual, _ = _actual_rotation(db.session.get(Game, 70), 1)
        assert actual['2'] == INNING_TWO


@pytest.mark.parametrize('alignment', [
    # Aiden at 1B and LF.
    dict(INNING_TWO, P='Jack', **{'1B': 'Aiden', 'LF': 'Aiden'}),
    # The new pitcher also listed in the field.
    dict(INNING_TWO, P='Jack', **{'1B': 'Aiden', 'LF': 'Jack'}),
], ids=['player_twice', 'pitcher_also_in_field'])
def test_a_chain_cannot_put_one_player_in_two_positions(monkeypatch, alignment):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)
    _patch_summary(monkeypatch, {'Jack': {'status': 'Available'}})

    response = client.post('/api/live-game/70/complete-pitcher-change', json={
        'base_sequence': 0, 'fast': True, 'new_pitcher_id': 10, 'alignment': alignment,
    })
    assert response.status_code == 409
    assert response.get_json()['message'] == (
        'A player cannot occupy more than one defensive position.'
    )
    assert _event_count(app) == 0
