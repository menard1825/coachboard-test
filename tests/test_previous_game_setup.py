"""Use Previous Game Setup on Prepare Game.

/api/game/<id>/previous-setup only reads: it finds the most recent earlier
game with a batting order or a 1st-inning defense and works out exactly what
of it fits today's game. The page then applies the result through the
existing writers (/add_lineup, /edit_lineup and /save_rotation), so these
tests also drive those writers with the preview's result, the way the page
does, and check the earlier game is never changed.
"""

import copy
from datetime import datetime

import pytest
from werkzeug.security import generate_password_hash


TEAM_ID = 1
OTHER_TEAM_ID = 2
NAMES = ['Alex', 'Blake', 'Casey', 'Drew', 'Eli', 'Finn', 'Gray', 'Harper', 'Indy', 'Jules']
POSITIONS = ['P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF']
LAST_GAME_DEFENSE = dict(zip(POSITIONS, NAMES))  # Alex pitched, Jules sat
LAST_GAME_ORDER = NAMES[:9]  # Jules didn't bat

TODAY = 10       # the game being prepared
LAST = 9         # most recent earlier game with a setup
EMPTY = 8        # newer than LAST, but its plan is empty
OLDER = 7        # an older game with a different setup
LATER = 11       # a game after today's, never a source


def _player_id(name):
    return NAMES.index(name) + 1


@pytest.fixture(name='app')
def _app(monkeypatch, tmp_path):
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{tmp_path / "previous_setup.db"}')

    from app import create_app
    from db import db
    from lineup_service import sync_lineup
    from models import Game, Lineup, Player, Rotation, Team, TeamMembership, User

    app = create_app()
    app.config.update(TESTING=True)

    with app.app_context():
        db.create_all()
        for team_id in (TEAM_ID, OTHER_TEAM_ID):
            db.session.add(Team(
                id=team_id, team_name=f'Team {team_id}', registration_code=f'code-{team_id}',
                age_group='12U', pitching_rule_set='MLB Pitch Smart', outfielder_count=3,
                timezone='America/Indiana/Indianapolis', batting_order_mode='bat_all',
            ))
        db.session.add(User(id=1, username='coach', full_name='Coach',
                            password_hash=generate_password_hash('password123')))
        db.session.flush()
        db.session.add(TeamMembership(user_id=1, team_id=TEAM_ID, role='Head Coach', player_order=[]))
        for index, name in enumerate(NAMES, start=1):
            db.session.add(Player(id=index, team_id=TEAM_ID, name=name))
        db.session.add(Player(id=50, team_id=OTHER_TEAM_ID, name='Zed'))

        games = [
            (OLDER, datetime(2026, 9, 20, 10), 'Older Opp'),
            (LAST, datetime(2026, 10, 3, 10), 'Tigers'),
            (EMPTY, datetime(2026, 10, 5, 10), 'Rained Out'),
            (TODAY, datetime(2027, 4, 10, 10), 'Visitors'),
            (LATER, datetime(2027, 4, 20, 10), 'Future Opp'),
        ]
        for game_id, date, opponent in games:
            db.session.add(Game(id=game_id, team_id=TEAM_ID, date=date, opponent=opponent, is_live=False))
        # Another team's game between LAST and TODAY must never be a source.
        db.session.add(Game(id=30, team_id=OTHER_TEAM_ID, date=datetime(2026, 10, 8), opponent='Other'))
        db.session.flush()

        roster = {player.name: player for player in db.session.query(Player).filter_by(team_id=TEAM_ID)}
        sync_lineup(Lineup(team_id=TEAM_ID), [roster[name] for name in LAST_GAME_ORDER],
                    title='Tigers lineup', associated_game_id=LAST)
        sync_lineup(Lineup(team_id=TEAM_ID), [roster[name] for name in reversed(NAMES)],
                    title='Older lineup', associated_game_id=OLDER)
        db.session.add(Rotation(title='Rotation for vs Tigers', team_id=TEAM_ID, associated_game_id=LAST,
                                innings={'1': dict(LAST_GAME_DEFENSE), '2': {'P': 'Blake'}}))
        db.session.add(Rotation(title='Rotation for vs Older', team_id=TEAM_ID, associated_game_id=OLDER,
                                innings={'1': {'C': 'Jules'}}))
        # The rained-out game has an empty plan: nothing reusable.
        db.session.add(Rotation(title='Rotation for vs Rained Out', team_id=TEAM_ID, associated_game_id=EMPTY,
                                innings={'1': {}, '2': {}}))
        db.session.add(Rotation(title='Rotation for vs Other', team_id=OTHER_TEAM_ID, associated_game_id=30,
                                innings={'1': {'C': 'Zed'}}))
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
        session['team_id'] = TEAM_ID
        session['role'] = 'Head Coach'
    return client


def _preview(app, game_id=TODAY):
    response = _client(app).get(f'/api/game/{game_id}/previous-setup')
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def _set_today(app, *, innings=None, absent=(), lineup=None, team_changes=None):
    from db import db
    from lineup_service import sync_lineup
    from models import Lineup, Player, PlayerGameAbsence, Rotation, Team

    with app.app_context():
        if innings is not None:
            db.session.add(Rotation(title='Rotation for vs Visitors', team_id=TEAM_ID,
                                    associated_game_id=TODAY, innings=innings))
        for name in absent:
            db.session.add(PlayerGameAbsence(player_id=_player_id(name), game_id=TODAY, team_id=TEAM_ID))
        if lineup is not None:
            roster = {player.name: player for player in db.session.query(Player).filter_by(team_id=TEAM_ID)}
            sync_lineup(Lineup(team_id=TEAM_ID), [roster[name] for name in lineup],
                        title='Today lineup', associated_game_id=TODAY)
        if team_changes:
            team = db.session.get(Team, TEAM_ID)
            for key, value in team_changes.items():
                setattr(team, key, value)
        db.session.commit()


def _snapshot(app, game_id):
    from db import db
    from lineup_service import lineup_to_dict
    from models import Lineup, Rotation

    with app.app_context():
        db.session.expire_all()
        lineup = db.session.query(Lineup).filter_by(team_id=TEAM_ID, associated_game_id=game_id).first()
        rotation = db.session.query(Rotation).filter_by(team_id=TEAM_ID, associated_game_id=game_id).first()
        lineup_data = lineup_to_dict(lineup) if lineup else None
        return {
            'lineup': (lineup.title, lineup_data['lineup_player_ids']) if lineup else None,
            'innings': copy.deepcopy(rotation.innings) if rotation else None,
        }


def _defense_by_position(preview):
    return {row['position']: row for row in preview['defense']['positions']}


# --- Finding the source game ----------------------------------------------

def test_the_most_recent_earlier_game_with_a_setup_is_the_source(app):
    data = _preview(app)

    assert data['status'] == 'success' and data['available'] is True
    # The rained-out game is newer but has nothing reusable; the later game
    # and the other team's game are never sources. Last season's games show
    # their year.
    assert data['source'] == {'game_id': LAST, 'opponent': 'Tigers', 'date_label': 'Sat, Oct 3, 2026',
                              'short_date': 'Oct 3, 2026'}


def test_a_game_with_no_earlier_setup_has_nothing_to_copy(app):
    data = _preview(app, game_id=OLDER)

    assert data['available'] is False
    assert data['reason'] == 'none'


def test_a_live_game_offers_nothing(app):
    from db import db
    from models import Game

    with app.app_context():
        db.session.get(Game, TODAY).is_live = True
        db.session.commit()

    assert _preview(app)['available'] is False
    assert _preview(app)['reason'] == 'live'


def test_another_teams_game_is_not_found(app):
    response = _client(app).get('/api/game/30/previous-setup')
    assert response.status_code == 404


# --- Starting defense -------------------------------------------------------

def test_the_pitcher_is_never_copied(app):
    defense = _preview(app)['defense']

    assert 'P' not in defense['proposed']
    assert 'P' not in _defense_by_position({'defense': defense})
    assert defense['previous_pitcher'] == 'Alex'
    assert defense['today_pitcher'] is None
    assert defense['proposed'] == {pos: LAST_GAME_DEFENSE[pos] for pos in POSITIONS if pos != 'P'}
    assert defense['copied_count'] == 8 and defense['open_count'] == 0


def test_todays_pitcher_stays_and_their_old_position_is_left_open(app):
    # Casey is today's starting pitcher; last game Casey played 1B.
    _set_today(app, innings={'1': {'P': 'Casey'}, '2': {}})

    data = _preview(app)
    defense = data['defense']
    rows = _defense_by_position(data)

    assert defense['proposed']['P'] == 'Casey'
    assert '1B' not in defense['proposed']
    assert rows['1B']['status'] == 'open' and rows['1B']['reason'] == 'pitching'
    # A P alone is not a defense the coach would lose.
    assert defense['replaces_current'] is False


def test_players_out_today_are_not_placed(app):
    _set_today(app, absent=['Drew', 'Gray'])

    data = _preview(app)
    rows = _defense_by_position(data)

    assert rows['2B'] == {'position': '2B', 'player': 'Drew', 'status': 'open',
                          'reason': 'out', 'label': 'Out today'}
    assert rows['LF']['reason'] == 'out'
    assert 'Drew' not in data['defense']['proposed'].values()
    assert 'Gray' not in data['defense']['proposed'].values()


def test_a_player_saved_twice_last_game_is_placed_once(app):
    from db import db
    from models import Rotation

    with app.app_context():
        rotation = db.session.query(Rotation).filter_by(associated_game_id=LAST).one()
        innings = copy.deepcopy(rotation.innings)
        innings['1']['RF'] = 'Blake'  # also at C: an old duplicate
        rotation.innings = innings
        db.session.commit()

    data = _preview(app)
    proposed = data['defense']['proposed']

    assert list(proposed.values()).count('Blake') == 1
    assert _defense_by_position(data)['RF']['reason'] == 'placed'


def test_a_position_todays_field_does_not_use_is_reported(app):
    _set_today(app, team_changes={'outfielder_count': 4})

    defense = _preview(app)['defense']

    assert defense['unused_positions'] == [{'position': 'CF', 'player': 'Harper'}]
    assert 'CF' not in defense['proposed']
    assert {row['position'] for row in defense['positions'] if row['status'] == 'open'} == {'LCF', 'RCF'}


def test_an_existing_defense_is_flagged_for_explicit_replacement(app):
    _set_today(app, innings={'1': {'P': 'Jules', 'C': 'Alex'}, '2': {'C': 'Eli'}})

    defense = _preview(app)['defense']

    assert defense['replaces_current'] is True
    assert defense['current_fielder_count'] == 1
    assert defense['current_alignment'] == {'P': 'Jules', 'C': 'Alex'}


# --- Batting order ------------------------------------------------------------

def test_bat_everyone_keeps_the_order_and_adds_new_players_at_the_bottom(app):
    _set_today(app, absent=['Casey'])

    lineup = _preview(app)['lineup']
    expected = [name for name in LAST_GAME_ORDER if name != 'Casey'] + ['Jules']

    assert [batter['name'] for batter in lineup['batters']] == expected
    assert lineup['player_ids'] == [_player_id(name) for name in expected]
    assert lineup['added'] == [{'player_id': _player_id('Jules'), 'name': 'Jules'}]
    assert lineup['skipped'] == [{'name': 'Casey', 'reason': 'out', 'label': 'Out today'}]
    assert lineup['batters'][-1]['added'] is True
    assert lineup['short_by'] == 0
    assert lineup['replaces_current'] is False


def test_fixed_lineup_keeps_the_top_of_the_order(app):
    _set_today(app, absent=['Alex'], team_changes={'batting_order_mode': 'fixed', 'fixed_lineup_size': 6})

    lineup = _preview(app)['lineup']

    assert [batter['name'] for batter in lineup['batters']] == LAST_GAME_ORDER[1:7]
    assert [player['name'] for player in lineup['trimmed']] == LAST_GAME_ORDER[7:]
    assert lineup['added'] == []


def test_a_removed_player_is_skipped(app):
    from db import db
    from models import Player

    with app.app_context():
        db.session.delete(db.session.get(Player, _player_id('Finn')))
        db.session.commit()

    data = _preview(app)

    assert {'name': 'Finn', 'reason': 'roster', 'label': 'No longer on the roster'} in data['lineup']['skipped']
    assert _defense_by_position(data)['SS']['reason'] == 'roster'


def test_an_existing_lineup_is_flagged_for_explicit_replacement(app):
    _set_today(app, lineup=['Jules', 'Alex'])

    lineup = _preview(app)['lineup']

    assert lineup['replaces_current'] is True
    assert lineup['current_count'] == 2
    assert lineup['current_title'] == 'Today lineup'
    assert lineup['current_id'] is not None


# --- Read-only, and applied through the existing writers ------------------------

def test_the_preview_changes_nothing(app):
    _set_today(app, innings={'1': {'P': 'Casey', 'C': 'Alex'}}, lineup=['Alex', 'Blake'])
    before = {game_id: _snapshot(app, game_id) for game_id in (TODAY, LAST, OLDER)}

    _preview(app)

    assert {game_id: _snapshot(app, game_id) for game_id in (TODAY, LAST, OLDER)} == before


def test_applying_the_preview_copies_today_and_never_changes_the_earlier_game(app):
    _set_today(app, innings={'1': {'P': 'Casey'}, '2': {'P': 'Jules', 'C': 'Blake'}, '3': {}}, absent=['Drew'])
    last_before = _snapshot(app, LAST)
    data = _preview(app)
    client = _client(app)

    from db import db
    from models import Rotation
    with app.app_context():
        rotation = db.session.query(Rotation).filter_by(associated_game_id=TODAY).one()
        rotation_id, innings = rotation.id, copy.deepcopy(rotation.innings)

    # What the page sends: today's plan with only the 1st inning replaced.
    innings['1'] = data['defense']['proposed']
    saved = client.post('/save_rotation', json={
        'id': rotation_id, 'title': 'Rotation for vs Visitors',
        'innings': innings, 'associated_game_id': TODAY,
    })
    assert saved.status_code == 200, saved.get_json()

    lineup = client.post('/add_lineup', json={
        'title': f"Lineup for vs {data['game_opponent']}",
        'lineup_player_ids': data['lineup']['player_ids'],
        'lineup_data': [batter['name'] for batter in data['lineup']['batters']],
        'associated_game_id': TODAY,
    })
    assert lineup.status_code == 200, lineup.get_json()

    today = _snapshot(app, TODAY)
    assert today['innings']['1']['P'] == 'Casey'
    assert today['innings']['1']['C'] == 'Blake'
    assert '1B' not in today['innings']['1']        # Casey is pitching
    assert '2B' not in today['innings']['1']        # Drew is Out
    assert 'Alex' not in today['innings']['1'].values()  # last game's pitcher
    assert today['innings']['2'] == {'P': 'Jules', 'C': 'Blake'}  # later innings untouched
    assert today['innings']['3'] == {}
    assert today['lineup'][1] == data['lineup']['player_ids']
    assert _player_id('Drew') not in today['lineup'][1]

    assert _snapshot(app, LAST) == last_before


def test_the_page_offers_the_action_only_when_there_is_a_source(app):
    client = _client(app)

    page = client.get(f'/game/{TODAY}').get_data(as_text=True)
    assert 'id="previousSetupLaunch"' in page
    assert 'id="previousSetupModal"' in page
    assert 'js/previous_game_setup.js' in page
    assert 'vs Tigers' in page

    first = client.get(f'/game/{OLDER}').get_data(as_text=True)
    assert 'id="previousSetupLaunch"' not in first
    assert 'js/previous_game_setup.js' not in first


# --- The card says what was copied, from today's data -------------------------------

def _page_state(app):
    import re
    page = _client(app).get(f'/game/{TODAY}').get_data(as_text=True)
    return re.search(r'id="previousSetupLaunch"[^>]*data-state="(\w+)"', page).group(1), page


def _copy(app, *, lineup=True, defense=True):
    data = _preview(app)
    client = _client(app)
    if defense:
        from db import db
        from models import Rotation
        with app.app_context():
            rotation = db.session.query(Rotation).filter_by(associated_game_id=TODAY).first()
            rotation_id = rotation.id if rotation else None
            innings = copy.deepcopy(rotation.innings) if rotation else {}
        innings['1'] = data['defense']['proposed']
        assert client.post('/save_rotation', json={
            'id': rotation_id, 'title': 'Rotation for vs Visitors', 'innings': innings,
            'associated_game_id': TODAY}).status_code == 200
    if lineup:
        assert client.post('/add_lineup', json={
            'title': 'Lineup for vs Visitors', 'lineup_player_ids': data['lineup']['player_ids'],
            'associated_game_id': TODAY}).status_code == 200
    return data


def test_the_card_offers_the_copy_before_anything_is_copied(app):
    state, page = _page_state(app)
    assert state == 'ready'
    assert 'Use Previous Game Setup' in page
    assert 'Review &amp; Copy' in page


def test_the_card_says_copied_when_both_parts_match(app):
    data = _copy(app)
    state, page = _page_state(app)

    assert state == 'copied'
    assert 'Copied from vs Tigers · Oct 3, 2026' in page
    assert f"Batting order: copied ({len(data['lineup']['player_ids'])} batters)" in page
    assert 'Starting defense: copied (8 fielders)' in page


def test_the_card_never_claims_a_part_that_was_not_copied(app):
    _copy(app, lineup=False)
    state, page = _page_state(app)

    assert state == 'partial'
    assert 'Partly copied from vs Tigers' in page
    assert 'Starting defense: copied (8 fielders)' in page
    assert 'Batting order: not copied' in page


def test_the_card_stops_saying_copied_once_the_coach_changes_it(app):
    _copy(app)
    from db import db
    from models import Rotation
    with app.app_context():
        rotation = db.session.query(Rotation).filter_by(associated_game_id=TODAY).one()
        innings = copy.deepcopy(rotation.innings)
        innings['1']['C'], innings['1']['1B'] = innings['1']['1B'], innings['1']['C']
        rotation_id = rotation.id
    assert _client(app).post('/save_rotation', json={
        'id': rotation_id, 'title': 'Rotation for vs Visitors', 'innings': innings,
        'associated_game_id': TODAY}).status_code == 200

    state, page = _page_state(app)
    assert state == 'partial'
    assert 'Starting defense: not copied' in page


# --- Readiness names what the plan needs ---------------------------------------------

def test_readiness_names_an_out_player_in_an_inning_and_the_starting_pitcher(app):
    _set_today(app, innings={'1': {**LAST_GAME_DEFENSE, 'P': 'Jules'}, '2': {'C': 'Drew'}}, absent=['Drew'])

    readiness = _client(app).get(f'/api/game-day/{TODAY}/readiness').get_json()['readiness']
    by_inning = {item['inning']: item for item in readiness['incomplete_innings']}

    assert readiness['starting_pitcher'] == 'Jules'
    assert by_inning['1']['unavailable'] == ['Drew']   # at 2B, marked Out
    assert by_inning['1']['missing'] == []
    assert by_inning['2']['unavailable'] == ['Drew']


def test_readiness_has_no_starting_pitcher_until_one_is_chosen(app):
    _set_today(app, innings={'1': {pos: name for pos, name in LAST_GAME_DEFENSE.items() if pos != 'P'}})

    readiness = _client(app).get(f'/api/game-day/{TODAY}/readiness').get_json()['readiness']
    first = next(item for item in readiness['incomplete_innings'] if item['inning'] == '1')

    assert readiness['starting_pitcher'] is None
    assert first == {'inning': '1', 'missing': ['P'], 'unavailable': []}
