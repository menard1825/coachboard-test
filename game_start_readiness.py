from copy import deepcopy

from db import db
from game_day_helpers import required_positions
from game_pitching_rules import rule_settings_payload
from models import Player, PlayerGameAbsence, Rotation


def can_start_game(game, team):
    """Return the one authoritative first-pitch readiness contract.

    This intentionally answers a narrower question than build_game_readiness():
    can the coach safely start Live Game right now? Batting order, later innings,
    pitching plans, and fair-play planning do not block first pitch.
    """
    team_id = team.id
    roster = db.session.query(Player).filter_by(team_id=team_id).all()
    absences = db.session.query(PlayerGameAbsence).filter_by(
        game_id=game.id,
        team_id=team_id,
    ).all()
    absent_ids = {row.player_id for row in absences}
    present = [player for player in roster if player.id not in absent_ids]
    present_names = {player.name for player in present}

    missing = []
    if not present:
        missing.append('Mark at least one player available for this game.')

    rotation = db.session.query(Rotation).filter_by(
        associated_game_id=game.id,
        team_id=team_id,
    ).first()
    inning_one = deepcopy((rotation.innings or {}).get('1', {}) if rotation else {})
    if not isinstance(inning_one, dict):
        inning_one = {}

    required = required_positions(team)
    starting_pitcher = inning_one.get('P')

    non_pitcher_missing = [
        position for position in required
        if position != 'P' and not inning_one.get(position)
    ]
    assigned_names = [
        inning_one.get(position)
        for position in required
        if inning_one.get(position)
    ]
    has_duplicate_assignments = len(assigned_names) != len(set(assigned_names))
    has_unavailable_assignment = any(
        name not in present_names
        for name in assigned_names
    )

    if non_pitcher_missing or has_duplicate_assignments or has_unavailable_assignment:
        missing.append('Finish the Inning 1 defense.')

    if not starting_pitcher:
        missing.append('Choose the starting pitcher for Inning 1.')
    elif starting_pitcher not in present_names:
        missing.append('The starting pitcher must be available for this game.')

    rule_payload = rule_settings_payload(team, game)
    if not rule_payload.get('effective'):
        missing.append('Select the game pitching rules / tracking method.')

    return {
        'ready': not missing,
        'missing': missing,
    }
