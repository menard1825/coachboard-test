from flask import Blueprint, jsonify, request

from db import db
from models import GameRotationEvent, PitchingOuting, Player
from utils import normalize_baseball_innings
from blueprints.live_game_api import (
    _actual_rotation,
    _authorized_context,
    _broadcast_state,
    _current_alignment,
    _event,
)


live_game_pitching_bp = Blueprint('live_game_pitching', __name__, url_prefix='/api/live-game')


@live_game_pitching_bp.before_app_request
def block_legacy_live_end_game():
    """Prevent old cached clients from bypassing the current finalization workflow."""
    if request.method == 'POST' and request.endpoint == 'live_game_api.end_game':
        return jsonify({
            'status': 'error',
            'message': 'Use the current End Game workflow so the live game is finalized correctly.'
        }), 409
    return None


def _append_pitcher(order, name):
    if name and name not in order:
        order.append(name)


def _actual_pitcher_order(game, team_id):
    """Return pitchers in first-appearance order from authoritative live history."""
    _, actual_rotation, events = _actual_rotation(game, team_id)
    order = []

    for event in events:
        if event.reverted:
            continue
        _append_pitcher(order, (event.before_alignment or {}).get('P'))
        _append_pitcher(order, (event.after_alignment or {}).get('P'))

    def inning_key(item):
        try:
            return float(item[0])
        except (TypeError, ValueError):
            return 9999

    for _, alignment in sorted((actual_rotation or {}).items(), key=inning_key):
        _append_pitcher(order, (alignment or {}).get('P'))

    _append_pitcher(order, _current_alignment(game, team_id, actual_rotation).get('P'))
    return order


def _parse_innings(item):
    if item.get('innings') not in (None, ''):
        return normalize_baseball_innings(item.get('innings'))

    whole = item.get('innings_whole')
    outs = item.get('innings_outs', 0)
    if whole in (None, ''):
        return None
    return normalize_baseball_innings(f'{whole}.{outs}')


def _ensure_end_game_event(game, team):
    """Persist a durable game-finalized marker exactly once."""
    already_finalized = db.session.query(GameRotationEvent).filter_by(
        game_id=game.id,
        team_id=team.id,
        event_type='End Game',
        reverted=False,
    ).first()
    if already_finalized:
        return

    _, actual_rotation, _ = _actual_rotation(game, team.id)
    current = _current_alignment(game, team.id, actual_rotation)
    _event(
        game,
        team.id,
        'End Game',
        str(game.live_current_inning or '1'),
        current,
        current,
    )


@live_game_pitching_bp.route('/<int:game_id>/end-with-pitching', methods=['POST'])
def end_with_pitching(game_id):
    """Finalize the game now and optionally save GameChanger pitching stats.

    `defer_pitching=true` ends the live game without creating or changing any
    PitchingOuting rows. Coaches can return later, after GameChanger is updated,
    and submit the real pitch counts/innings through this same endpoint.
    """
    user, team, game = _authorized_context(game_id)
    if not game:
        return jsonify({'status': 'error', 'message': 'Unauthorized or game not found.'}), 403

    data = request.get_json(silent=True) or {}
    defer_pitching = bool(data.get('defer_pitching'))
    submitted = data.get('counts') or []
    submitted_by_player = {}
    for item in submitted:
        try:
            submitted_by_player[int(item.get('player_id'))] = item
        except (TypeError, ValueError):
            continue

    pitcher_order = _actual_pitcher_order(game, team.id)
    missing_pitch_counts = []
    missing_innings = []

    if not defer_pitching:
        players_by_name = {
            p.name: p
            for p in db.session.query(Player).filter_by(team_id=team.id).all()
        }

        for index, pitcher_name in enumerate(pitcher_order):
            player = players_by_name.get(pitcher_name)
            if not player:
                continue
            item = submitted_by_player.get(player.id, {})

            raw_pitches = item.get('pitches')
            pitches = None
            if raw_pitches not in (None, ''):
                try:
                    pitches = int(raw_pitches)
                    if pitches < 0:
                        raise ValueError
                except (TypeError, ValueError):
                    return jsonify({'status': 'error', 'message': f'Invalid pitch count for {player.name}.'}), 400

            innings = _parse_innings(item)
            if item.get('innings') not in (None, '') or item.get('innings_whole') not in (None, ''):
                if innings is None:
                    return jsonify({'status': 'error', 'message': f'Invalid innings for {player.name}. Use full innings plus 0, 1, or 2 outs.'}), 400

            if pitches is None:
                missing_pitch_counts.append(player.name)
            if innings is None:
                missing_innings.append(player.name)

            existing = db.session.query(PitchingOuting).filter_by(
                game_id=game.id,
                player_id=player.id,
                team_id=team.id,
            ).order_by(PitchingOuting.id.asc()).all()

            if existing:
                outing = existing[0]
                for duplicate in existing[1:]:
                    db.session.delete(duplicate)
            else:
                outing = PitchingOuting(
                    game_id=game.id,
                    player_id=player.id,
                    team_id=team.id,
                )
                db.session.add(outing)

            outing.date = game.date
            outing.opponent = game.opponent
            outing.outing_type = 'Game'
            outing.pitcher_type = 'Starter' if index == 0 else 'Reliever'
            outing.pitches = pitches
            outing.innings = innings

    _ensure_end_game_event(game, team)
    game.is_live = False
    db.session.commit()
    state = _broadcast_state(game.id, team.id)

    warnings = []
    if not defer_pitching:
        if missing_pitch_counts:
            warnings.append('Missing pitch count: ' + ', '.join(missing_pitch_counts))
        if missing_innings:
            warnings.append('Missing innings: ' + ', '.join(missing_innings))

    return jsonify({
        'status': 'success',
        'state': state,
        'pitchers': pitcher_order,
        'pitching_deferred': defer_pitching,
        'warnings': warnings,
    })
