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


@pytest.mark.parametrize('pitch_count_summary, expected_message_fragment', [
    ({'Jack': {'status': 'Resting', 'status_detail': '40 game pitches on Mon, Aug 24 require 2 day(s) rest.'}}, 'Resting'),
    ({'Jack': {'status': 'Pitch Count Incomplete'}}, 'Pitch Count Incomplete'),
    ({'Jack': {'status': 'Innings Incomplete'}}, 'Innings Incomplete'),
    ({'Jack': {'status': 'Verify Rules'}}, 'Verify Rules'),
    ({'Jack': {'status': 'Eligibility Error', 'status_detail': "CoachBoard could not calculate pitching eligibility."}}, 'Eligibility Error'),
    ({}, "could not verify Jack's pitching eligibility"),
    ({'Jack': {'status': ''}}, "could not verify Jack's pitching eligibility"),
    ({'Jack': {'status': 'Something Nobody Has Invented Yet'}}, 'Something Nobody Has Invented Yet'),
], ids=[
    'resting', 'pitch_count_incomplete', 'innings_incomplete', 'verify_rules',
    'eligibility_error', 'missing_summary', 'empty_status', 'unknown_future_status',
])
def test_advance_inning_ineligible_new_pitcher_is_rejected(monkeypatch, pitch_count_summary, expected_message_fragment):
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
    assert payload['code'] == 'pitcher_not_eligible'
    assert expected_message_fragment in payload['message']

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
    ({}, "could not verify Carter's pitching eligibility"),
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



def test_complete_pitcher_change_pitch_anyway_allows_warned_pitcher(
    monkeypatch,
):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    from blueprints import live_game_bulk_api as bulk_module

    monkeypatch.setattr(
        bulk_module,
        'get_authoritative_live_state',
        lambda game_id, team_id: {
            'pitch_count_summary': {
                'Carter': {
                    'status': 'Needs Rest',
                    'daily': 42,
                    'status_detail': 'Pitched yesterday',
                },
            },
        },
    )

    # Carter moves from 1B to P. The outgoing pitcher sits and
    # 1B intentionally remains open for On the Field.
    proposed = {
        'P': 'Carter',
        'C': 'Bennett',
        '2B': 'Drew',
        '3B': 'Eli',
        'SS': 'Finn',
        'LF': 'Gavin',
        'CF': 'Hudson',
        'RF': 'Isaac',
    }

    response = client.post(
        '/api/live-game/70/complete-pitcher-change',
        json={
            'base_sequence': 0,
            'fast': True,
            'new_pitcher_id': 3,
            'alignment': proposed,
            'pitch_anyway': True,
        },
    )

    assert response.status_code == 200

    payload = response.get_json()

    assert (
        payload['delta']['current_alignment']['P']
        == 'Carter'
    )

    assert (
        '1B'
        not in payload['delta']['current_alignment']
    )

    assert 'Aiden' in {
        player['name']
        for player in payload['delta']['bench']
    }

    assert (
        payload['delta']['event']['event_type']
        == 'Pitcher Change'
    )

    from db import db
    from models import GameRotationEvent

    with app.app_context():
        assert (
            db.session.query(GameRotationEvent)
            .filter_by(
                game_id=70,
                team_id=1,
            )
            .count()
            == 1
        )


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
