from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, request, session
from sqlalchemy.orm import joinedload

from db import db
from models import (
    Game,
    GameRotationEvent,
    PitchingOuting,
    Player,
    PlayerGameAbsence,
    PlayerPracticeAbsence,
    PracticePlan,
    Rotation,
    Team,
)
from season_stats import build_season_usage_dashboard
from actual_stats import calculate_actual_position_game_stats
from utils import calculate_cumulative_pitching_stats


stats_dashboard_bp = Blueprint('stats_dashboard', __name__, url_prefix='/api')


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


def _game_date(game):
    return game.date.date() if game and game.date else None


@stats_dashboard_bp.route('/stats-dashboard')
def stats_dashboard():
    if 'logged_in' not in session or not session.get('team_id'):
        return jsonify({'status': 'error', 'message': 'Unauthorized.'}), 401

    team_id = session['team_id']
    team = db.session.get(Team, team_id)
    if not team:
        return jsonify({'status': 'error', 'message': 'Team not found.'}), 404

    roster = db.session.query(Player).filter_by(team_id=team_id).all()
    games = db.session.query(Game).filter_by(team_id=team_id).all()
    rotations = db.session.query(Rotation).filter_by(team_id=team_id).all()
    events = db.session.query(GameRotationEvent).filter_by(team_id=team_id).order_by(
        GameRotationEvent.game_id.asc(),
        GameRotationEvent.sequence.asc(),
        GameRotationEvent.id.asc(),
    ).all()
    game_absences = db.session.query(PlayerGameAbsence).filter_by(team_id=team_id).all()
    practices = db.session.query(PracticePlan).filter_by(team_id=team_id).all()
    practice_absences = db.session.query(PlayerPracticeAbsence).filter_by(team_id=team_id).all()
    outings = db.session.query(PitchingOuting).options(joinedload(PitchingOuting.player)).filter_by(team_id=team_id).all()

    tz = ZoneInfo(team.timezone or 'America/Indiana/Indianapolis')
    today = datetime.now(tz).date()
    live_game_ids = {event.game_id for event in events if event.game_id and not event.reverted}
    rotation_game_ids = {rotation.associated_game_id for rotation in rotations if rotation.associated_game_id}

    # Match the existing stats philosophy: Live Game history is authoritative.
    # A legacy saved rotation is treated as played only after its calendar date.
    eligible_games = [
        game for game in games
        if game.id in live_game_ids
        or (game.id in rotation_game_ids and _game_date(game) and _game_date(game) < today)
    ]
    eligible_games.sort(key=lambda game: (_game_date(game) or today, game.id or 0), reverse=True)

    scope = (request.args.get('scope') or 'season').strip().lower()
    requested_start = _parse_date(request.args.get('start'))
    requested_end = _parse_date(request.args.get('end'))
    selected_games = list(eligible_games)
    effective_start = requested_start
    effective_end = requested_end

    if scope == 'last5':
        selected_games = eligible_games[:5]
        dates = [_game_date(game) for game in selected_games if _game_date(game)]
        effective_start = min(dates) if dates else None
        effective_end = max(dates) if dates else None
    elif scope == 'range':
        if not requested_start or not requested_end:
            return jsonify({'status': 'error', 'message': 'Choose both a start and end date.'}), 400
        if requested_start > requested_end:
            return jsonify({'status': 'error', 'message': 'Start date must be before end date.'}), 400
        selected_games = [
            game for game in eligible_games
            if _game_date(game) and requested_start <= _game_date(game) <= requested_end
        ]
    else:
        scope = 'season'
        effective_start = None
        effective_end = None

    selected_game_ids = {game.id for game in selected_games}
    selected_rotations = [rotation for rotation in rotations if rotation.associated_game_id in selected_game_ids]
    selected_events = [event for event in events if event.game_id in selected_game_ids]
    selected_game_absences = [absence for absence in game_absences if absence.game_id in selected_game_ids]

    completed_practices = [plan for plan in practices if plan.date and plan.date.date() <= today]
    if effective_start or effective_end:
        selected_practices = [
            plan for plan in completed_practices
            if (not effective_start or plan.date.date() >= effective_start)
            and (not effective_end or plan.date.date() <= effective_end)
        ]
    else:
        selected_practices = completed_practices
    selected_practice_ids = {plan.id for plan in selected_practices}
    selected_practice_absences = [
        absence for absence in practice_absences
        if absence.practice_plan_id in selected_practice_ids
    ]

    dashboard = build_season_usage_dashboard(
        roster,
        selected_rotations,
        selected_events,
        selected_games,
        selected_game_absences,
        selected_practices,
        selected_practice_absences,
        outings,
    )

    raw_position_games = calculate_actual_position_game_stats(
        roster, selected_rotations, selected_events, selected_games
    )

    selected_date_opponents = {
        (game.date.date(), game.opponent)
        for game in selected_games if game.date
    }
    selected_outings = [
        outing for outing in outings
        if str(outing.outing_type or 'Game').strip().lower() == 'game'
        and (
            outing.game_id in selected_game_ids
            or (
                outing.game_id is None
                and outing.date
                and (outing.date.date(), outing.opponent) in selected_date_opponents
            )
        )
    ]
    raw_pitching = {
        player.name: calculate_cumulative_pitching_stats(player.id, selected_outings)
        for player in roster
        if any(outing.player_id == player.id for outing in selected_outings)
    }

    dashboard.update({
        'status': 'success',
        'scope': {
            'name': scope,
            'start': effective_start.isoformat() if effective_start else None,
            'end': effective_end.isoformat() if effective_end else None,
            'label': 'Last 5 Games' if scope == 'last5' else ('Custom Range' if scope == 'range' else 'Full Season'),
        },
        'raw': {
            'position_game_appearances': raw_position_games,
            'pitching': raw_pitching,
        },
    })
    return jsonify(dashboard)
