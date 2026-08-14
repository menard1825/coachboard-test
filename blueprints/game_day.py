from datetime import datetime, timedelta

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

from db import db
from game_day_helpers import build_actual_game_report, build_game_readiness, team_now
from models import Game, Team


game_day_bp = Blueprint('game_day', __name__)


def _team_context():
    team_id = session.get('team_id')
    if not team_id:
        return None
    return db.session.get(Team, team_id)


@game_day_bp.route('/game-day')
def game_day_home():
    team = _team_context()
    if not team or 'logged_in' not in session:
        return redirect(url_for('auth.login'))

    now = team_now(team)
    today = now.date()
    day_start = datetime.combine(today, datetime.min.time())
    next_day = day_start + timedelta(days=1)

    todays_games = db.session.query(Game).filter(
        Game.team_id == team.id,
        Game.date >= day_start,
        Game.date < next_day,
    ).order_by(Game.date.asc(), Game.start_time.asc(), Game.id.asc()).all()

    focus_games = todays_games
    focus_label = "Today's Games"
    if not focus_games:
        next_game = db.session.query(Game).filter(
            Game.team_id == team.id,
            Game.date >= next_day,
        ).order_by(Game.date.asc(), Game.start_time.asc(), Game.id.asc()).first()
        focus_games = [next_game] if next_game else []
        focus_label = 'Next Game'

    game_cards = [
        {'game': game, 'readiness': build_game_readiness(game, team)}
        for game in focus_games
        if game is not None
    ]

    focus_ids = {item['game'].id for item in game_cards}
    upcoming_query = db.session.query(Game).filter(
        Game.team_id == team.id,
        Game.date >= next_day,
    )
    if focus_ids:
        upcoming_query = upcoming_query.filter(~Game.id.in_(focus_ids))
    upcoming = upcoming_query.order_by(Game.date.asc(), Game.start_time.asc(), Game.id.asc()).limit(5).all()

    return render_template(
        'game_day.html',
        current_team=team,
        game_cards=game_cards,
        focus_label=focus_label,
        local_now=now,
        upcoming=upcoming,
    )


@game_day_bp.route('/api/game-day/<int:game_id>/readiness')
def readiness_api(game_id):
    team = _team_context()
    if not team or 'logged_in' not in session:
        return jsonify({'status': 'error', 'message': 'Unauthorized.'}), 401
    game = db.session.query(Game).filter_by(id=game_id, team_id=team.id).first()
    if not game:
        return jsonify({'status': 'error', 'message': 'Game not found.'}), 404
    return jsonify({'status': 'success', 'readiness': build_game_readiness(game, team)})


@game_day_bp.route('/game-day/<int:game_id>/report')
def game_report(game_id):
    team = _team_context()
    if not team or 'logged_in' not in session:
        return redirect(url_for('auth.login'))
    game = db.session.query(Game).filter_by(id=game_id, team_id=team.id).first()
    if not game:
        return redirect(url_for('game_day.game_day_home'))

    readiness = build_game_readiness(game, team)
    report = build_actual_game_report(game, team)
    return render_template(
        'game_report.html',
        current_team=team,
        game=game,
        readiness=readiness,
        report=report,
    )


@game_day_bp.route('/game-day/<int:game_id>/notes', methods=['POST'])
def save_game_notes(game_id):
    team = _team_context()
    if not team or 'logged_in' not in session:
        return redirect(url_for('auth.login'))
    game = db.session.query(Game).filter_by(id=game_id, team_id=team.id).first()
    if not game:
        flash('Game not found.', 'danger')
        return redirect(url_for('game_day.game_day_home'))

    game.game_notes = str(request.form.get('game_notes') or '').strip()
    db.session.commit()
    flash('Game notes saved.', 'success')
    return redirect(url_for('game_day.game_report', game_id=game.id))
