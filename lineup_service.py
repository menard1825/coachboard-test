"""Validation, compatibility, and serialization helpers for batting lineups."""

from models import Game, Lineup, LineupEntry, Player
from db import db
from utils import model_to_dict


class LineupValidationError(ValueError):
    pass


def _legacy_names(lineup):
    names = lineup.lineup_positions or []
    if isinstance(names, str):
        import json
        try:
            names = json.loads(names)
        except (TypeError, ValueError):
            names = []
    return [str(name).strip() for name in names if str(name).strip()] if isinstance(names, list) else []


def _legacy_entries(lineup):
    """Resolve old name-only data without changing it or requiring a migration."""
    players = db.session.query(Player).filter_by(team_id=lineup.team_id).all()
    by_name = {}
    duplicates = set()
    for player in players:
        if player.name in by_name:
            duplicates.add(player.name)
        by_name[player.name] = player

    entries = []
    for index, name in enumerate(_legacy_names(lineup), start=1):
        player = None if name in duplicates else by_name.get(name)
        entries.append({
            'player_id': player.id if player else None,
            'name': player.name if player else name,
            'player_name_snapshot': name,
            'batting_order': index,
            'available': player is not None,
        })
    return entries


def lineup_to_dict(lineup):
    if lineup is None:
        return None

    result = model_to_dict(lineup)
    normalized = []
    for entry in sorted(lineup.entries or [], key=lambda item: item.batting_order):
        current_name = entry.player.name if entry.player else entry.player_name_snapshot
        normalized.append({
            'player_id': entry.player_id,
            'name': current_name,
            'player_name_snapshot': entry.player_name_snapshot,
            'batting_order': entry.batting_order,
            'available': entry.player is not None,
        })
    if not normalized:
        normalized = _legacy_entries(lineup)

    result['lineup_entries'] = normalized
    result['lineup_player_ids'] = [entry['player_id'] for entry in normalized if entry['player_id'] is not None]
    result['lineup_positions'] = [entry['name'] for entry in normalized]
    return result


def validate_lineup_payload(payload, team_id):
    if not isinstance(payload, dict):
        raise LineupValidationError('Invalid lineup data.')

    title = str(payload.get('title') or '').strip()
    if not title:
        raise LineupValidationError('A lineup title is required.')
    if len(title) > 120:
        raise LineupValidationError('Lineup titles must be 120 characters or fewer.')

    raw_player_ids = payload.get('lineup_player_ids')
    players = []
    if raw_player_ids is not None:
        if not isinstance(raw_player_ids, list):
            raise LineupValidationError('Lineup players must be provided as a list.')
        try:
            player_ids = [int(player_id) for player_id in raw_player_ids]
        except (TypeError, ValueError):
            raise LineupValidationError('One or more lineup players are invalid.')
        if len(player_ids) != len(set(player_ids)):
            raise LineupValidationError('A player can only appear once in a lineup.')
        roster = db.session.query(Player).filter(
            Player.team_id == team_id,
            Player.id.in_(player_ids),
        ).all() if player_ids else []
        by_id = {player.id: player for player in roster}
        missing = [player_id for player_id in player_ids if player_id not in by_id]
        if missing:
            raise LineupValidationError('One or more players are not on this team.')
        players = [by_id[player_id] for player_id in player_ids]
    else:
        raw_names = payload.get('lineup_data')
        if not isinstance(raw_names, list):
            raise LineupValidationError('Lineup players must be provided as a list.')
        names = [str(name).strip() for name in raw_names]
        if any(not name for name in names):
            raise LineupValidationError('Lineup player names cannot be blank.')
        if len(names) != len(set(names)):
            raise LineupValidationError('A player can only appear once in a lineup.')
        roster = db.session.query(Player).filter_by(team_id=team_id).all()
        by_name = {}
        duplicate_names = set()
        for player in roster:
            if player.name in by_name:
                duplicate_names.add(player.name)
            by_name[player.name] = player
        missing = [name for name in names if name not in by_name or name in duplicate_names]
        if missing:
            raise LineupValidationError('One or more players could not be matched uniquely to this team.')
        players = [by_name[name] for name in names]

    if not players:
        raise LineupValidationError('Add at least one player to the batting order.')

    associated_game_id = payload.get('associated_game_id')
    if associated_game_id in ('', None):
        associated_game_id = None
    else:
        try:
            associated_game_id = int(associated_game_id)
        except (TypeError, ValueError):
            raise LineupValidationError('The selected game is invalid.')
        game = db.session.query(Game).filter_by(id=associated_game_id, team_id=team_id).first()
        if not game:
            raise LineupValidationError('The selected game was not found for this team.')

    raw_default = payload.get('is_default', False)
    is_default = (
        raw_default is True
        or str(raw_default).strip().lower() in {'1', 'true', 'yes', 'on'}
    ) and associated_game_id is None
    return title, players, associated_game_id, is_default


def sync_lineup(lineup, players, *, title, associated_game_id, is_default=False):
    lineup.title = title
    lineup.associated_game_id = associated_game_id
    lineup.is_default = bool(is_default and associated_game_id is None)
    lineup.lineup_positions = [player.name for player in players]

    if lineup.id is None:
        db.session.add(lineup)
        db.session.flush()
    else:
        lineup.entries.clear()
        db.session.flush()

    for batting_order, player in enumerate(players, start=1):
        lineup.entries.append(LineupEntry(
            player_id=player.id,
            player_name_snapshot=player.name,
            batting_order=batting_order,
        ))

    if lineup.is_default:
        db.session.query(Lineup).filter(
            Lineup.team_id == lineup.team_id,
            Lineup.associated_game_id.is_(None),
            Lineup.id != lineup.id,
        ).update({'is_default': False}, synchronize_session='fetch')

    return lineup
