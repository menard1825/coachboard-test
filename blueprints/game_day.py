from datetime import datetime, timedelta

from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, session, url_for

from db import db
from extensions import socketio
from game_day_helpers import build_actual_game_report, build_game_readiness, team_now
from game_pitching_rules import (
    GamePitchingRule,
    RULE_SET_OPTIONS,
    game_rule_context,
    game_rule_override,
    install_request_rule_adapters,
    rule_settings_payload,
)
from models import Game, Lineup, PlayerPitchTarget, Rotation, Team


game_day_bp = Blueprint('game_day', __name__)


def _team_context():
    team_id = session.get('team_id')
    if not team_id:
        return None
    return db.session.get(Team, team_id)


def _readiness_for_game(game, team):
    # build_game_readiness still uses the established team-based rules engine.
    # Temporarily expose this game's effective rules without changing Team data.
    with game_rule_context(team, game):
        return build_game_readiness(game, team)


@game_day_bp.before_app_request
def apply_game_pitching_rule_context():
    """Make per-game pitching rules visible to existing game-state calculators."""
    install_request_rule_adapters()

    if 'logged_in' not in session or not session.get('team_id'):
        return None

    # Game Day's own endpoints need the real team default so they can display and
    # edit the override correctly. Their calculations use _readiness_for_game().
    if str(request.endpoint or '').startswith('game_day.'):
        return None

    game_id = (request.view_args or {}).get('game_id')
    try:
        game_id = int(game_id)
    except (TypeError, ValueError):
        return None

    override = game_rule_override(game_id, session['team_id'])
    if override and override.rule_set in RULE_SET_OPTIONS:
        g.coachboard_game_pitching_rule = override.rule_set
    return None


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
        {'game': game, 'readiness': _readiness_for_game(game, team)}
        for game in focus_games
        if game is not None
    ]

    focus_ids = {item['game'].id for item in game_cards}

    # Keep postgame work visible after game day. This is especially important for
    # GameChanger, whose final pitching numbers may not be available immediately.
    followup_candidates = db.session.query(Game).filter(
        Game.team_id == team.id,
        Game.date < next_day,
    ).order_by(Game.date.desc(), Game.id.desc()).limit(20).all()
    followup_cards = []
    for game in followup_candidates:
        if game.id in focus_ids:
            continue
        readiness = _readiness_for_game(game, team)
        if readiness['status'] in {'GC STATS PENDING', 'NEEDS POSTGAME'}:
            followup_cards.append({'game': game, 'readiness': readiness})
        if len(followup_cards) >= 6:
            break

    # Game Day doubles as the schedule manager. Keep a useful upcoming window
    # here instead of forcing coaches back to the legacy home-page Games tab.
    upcoming_query = db.session.query(Game).filter(
        Game.team_id == team.id,
        Game.date >= next_day,
    )
    if focus_ids:
        upcoming_query = upcoming_query.filter(~Game.id.in_(focus_ids))
    upcoming = upcoming_query.order_by(Game.date.asc(), Game.start_time.asc(), Game.id.asc()).limit(12).all()

    # Preserve schedule history too. The Game Day redesign originally only kept
    # today's/next game, unfinished postgame work, and future games visible,
    # which made completed past games appear to have disappeared. Historical
    # games stay lightweight here: no readiness calculation is needed just to
    # browse, open, or view their report.
    past_games = db.session.query(Game).filter(
        Game.team_id == team.id,
        Game.date < day_start,
    ).order_by(Game.date.desc(), Game.start_time.desc(), Game.id.desc()).all()

    return render_template(
        'game_day.html',
        current_team=team,
        game_cards=game_cards,
        followup_cards=followup_cards,
        focus_label=focus_label,
        local_now=now,
        upcoming=upcoming,
        past_games=past_games,
    )


@game_day_bp.route('/api/game-day/pitching-rule-options')
def pitching_rule_options():
    team = _team_context()
    if not team or 'logged_in' not in session:
        return jsonify({'status': 'error', 'message': 'Unauthorized.'}), 401
    return jsonify({
        'status': 'success',
        'team_default': team.pitching_rule_set or 'MLB Pitch Smart',
        'options': list(RULE_SET_OPTIONS),
    })


@game_day_bp.route('/api/game-day/<int:game_id>/pitching-rules', methods=['GET', 'POST'])
def game_pitching_rules(game_id):
    team = _team_context()
    if not team or 'logged_in' not in session:
        return jsonify({'status': 'error', 'message': 'Unauthorized.'}), 401

    game = db.session.query(Game).filter_by(id=game_id, team_id=team.id).first()
    if not game:
        return jsonify({'status': 'error', 'message': 'Game not found.'}), 404

    if request.method == 'POST':
        if game.is_live:
            return jsonify({
                'status': 'error',
                'message': 'Pitching rules cannot be changed while the game is live. End Live Game first.',
            }), 409

        data = request.get_json(silent=True) or request.form
        requested = str(data.get('rule_set') or '').strip()
        override = game_rule_override(game.id, team.id)

        if requested.lower() in {'', 'default', 'team default', 'team_default'}:
            if override:
                db.session.delete(override)
        elif requested not in RULE_SET_OPTIONS:
            return jsonify({'status': 'error', 'message': 'Unsupported pitching rule set.'}), 400
        else:
            if not override:
                override = GamePitchingRule(game_id=game.id, team_id=team.id, rule_set=requested)
                db.session.add(override)
            else:
                override.rule_set = requested

        db.session.commit()
        socketio.emit('data_updated', {'message': f'Pitching rules updated for game vs {game.opponent}.'})

    return jsonify({'status': 'success', **rule_settings_payload(team, game)})


@game_day_bp.route('/game-day/add', methods=['POST'])
def add_game():
    """Create a game directly from the Game Day / Schedule experience."""
    team = _team_context()
    if not team or 'logged_in' not in session:
        return redirect(url_for('auth.login'))

    game_date_raw = str(request.form.get('game_date') or '').strip()
    opponent = str(request.form.get('game_opponent') or '').strip()
    requested_rule = str(request.form.get('pitching_rule_set') or '').strip()
    if not game_date_raw or not opponent:
        flash('Game date and opponent are required.', 'danger')
        return redirect(url_for('game_day.game_day_home'))
    if requested_rule and requested_rule not in RULE_SET_OPTIONS:
        flash('Invalid pitching rule set.', 'danger')
        return redirect(url_for('game_day.game_day_home'))

    try:
        game_date = datetime.strptime(game_date_raw, '%Y-%m-%d')
    except ValueError:
        flash('Invalid game date.', 'danger')
        return redirect(url_for('game_day.game_day_home'))

    game = Game(
        date=game_date,
        start_time=str(request.form.get('game_start_time') or '').strip(),
        opponent=opponent,
        location=str(request.form.get('game_location') or '').strip(),
        game_notes=str(request.form.get('game_notes') or '').strip(),
        team_id=team.id,
    )
    db.session.add(game)
    db.session.flush()

    if requested_rule:
        db.session.add(GamePitchingRule(
            game_id=game.id,
            team_id=team.id,
            rule_set=requested_rule,
        ))

    db.session.commit()
    socketio.emit('data_updated', {'message': f'Game vs {game.opponent} added.'})
    flash(f'Game vs {game.opponent} added.', 'success')
    return redirect(url_for('gameday.game_management', game_id=game.id))


@game_day_bp.route('/game-day/<int:game_id>/delete', methods=['POST'])
def delete_game(game_id):
    """Delete a scheduled/test game from Game Day without allowing live-game loss."""
    team = _team_context()
    if not team or 'logged_in' not in session:
        return jsonify({'status': 'error', 'message': 'Unauthorized.'}), 401

    game = db.session.query(Game).filter_by(id=game_id, team_id=team.id).first()
    if not game:
        return jsonify({'status': 'error', 'message': 'Game not found.'}), 404
    if game.is_live:
        return jsonify({
            'status': 'error',
            'message': 'A live game cannot be deleted. End the game first.',
        }), 409

    # Planning records use integer game ids rather than ORM relationships, so
    # remove them explicitly before deleting the game.
    db.session.query(Lineup).filter_by(
        associated_game_id=game.id,
        team_id=team.id,
    ).delete(synchronize_session=False)
    db.session.query(Rotation).filter_by(
        associated_game_id=game.id,
        team_id=team.id,
    ).delete(synchronize_session=False)
    db.session.query(PlayerPitchTarget).filter_by(
        game_id=game.id,
        team_id=team.id,
    ).delete(synchronize_session=False)
    db.session.query(GamePitchingRule).filter_by(
        game_id=game.id,
        team_id=team.id,
    ).delete(synchronize_session=False)

    # Next-inning prep is defined in the compatibility live-game module. Import
    # locally to avoid coupling Game Day module initialization to that model.
    from blueprints.live_game_ui import GameNextInningPrep
    db.session.query(GameNextInningPrep).filter_by(
        game_id=game.id,
        team_id=team.id,
    ).delete(synchronize_session=False)

    opponent = game.opponent
    db.session.delete(game)
    db.session.commit()
    socketio.emit('data_updated', {'message': f'Game vs {opponent} deleted.'})
    return jsonify({
        'status': 'success',
        'message': f'Game vs {opponent} deleted.',
    })


@game_day_bp.route('/api/game-day/<int:game_id>/readiness')
def readiness_api(game_id):
    team = _team_context()
    if not team or 'logged_in' not in session:
        return jsonify({'status': 'error', 'message': 'Unauthorized.'}), 401
    game = db.session.query(Game).filter_by(id=game_id, team_id=team.id).first()
    if not game:
        return jsonify({'status': 'error', 'message': 'Game not found.'}), 404
    return jsonify({'status': 'success', 'readiness': _readiness_for_game(game, team)})


@game_day_bp.route('/game-day/<int:game_id>/report')
def game_report(game_id):
    team = _team_context()
    if not team or 'logged_in' not in session:
        return redirect(url_for('auth.login'))
    game = db.session.query(Game).filter_by(id=game_id, team_id=team.id).first()
    if not game:
        return redirect(url_for('game_day.game_day_home'))

    readiness = _readiness_for_game(game, team)
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
