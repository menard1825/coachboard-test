from flask import Blueprint, request, redirect, url_for, flash, session, render_template, jsonify
from models import PitchingOuting, Team, Game, Player, PlayerPitchTarget
from db import db
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from extensions import socketio
from utils import (
    get_pitching_rules_for_team,
    calculate_pitch_count_summary,
    normalize_baseball_innings,
)
from datetime import datetime
from functools import wraps

pitching_bp = Blueprint('pitching', __name__, template_folder='templates')

OUTING_TYPES = {'Game', 'Practice', 'External/Lesson'}
PITCHER_TYPES = {'Starter', 'Reliever'}


def parse_date(date_str):
    """Try to parse a date string with the legacy formats CoachBoard has used."""
    if not date_str:
        return None
    for fmt in ('%Y-%m-%d', '%A, %m/%d/%y, %I:%M %p', '%A, %m/%d/%y'):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            pass
    return None


def _outing_type(value):
    value = str(value or 'Game').strip()
    if value == 'Lesson':
        value = 'External/Lesson'
    return value if value in OUTING_TYPES else 'Game'


def _innings_from_form(form):
    """Return storage-compatible baseball innings (.0/.1/.2) or None."""
    if 'innings_whole' in form or 'innings_outs' in form:
        whole = str(form.get('innings_whole', '')).strip()
        outs = str(form.get('innings_outs', '0')).strip()
        if whole == '':
            return None
        if outs not in {'0', '1', '2'}:
            return None
        raw = f'{whole}.{outs}'
    else:
        raw = form.get('innings')
    return normalize_baseball_innings(raw)


def _redirect_back(default_endpoint='pitching.pitching_page'):
    return redirect(request.referrer or url_for(default_endpoint))


@pitching_bp.route('/add_pitching', methods=['POST'])
def add_pitching():
    team_id = session.get('team_id')
    if not team_id:
        flash('Please select a team first.', 'warning')
        return redirect(url_for('auth.login'))

    game_id_raw = request.form.get('game_id')
    game = None
    if game_id_raw:
        try:
            game_id = int(game_id_raw)
        except (TypeError, ValueError):
            flash('Invalid game.', 'danger')
            return _redirect_back()
        game = db.session.query(Game).filter_by(id=game_id, team_id=team_id).first()
        if not game:
            flash('Game not found.', 'danger')
            return _redirect_back()
    else:
        game_id = None

    # A record entered from Game Management is always a game outing.
    outing_type = 'Game' if game else _outing_type(request.form.get('outing_type'))

    try:
        pitch_count = int(request.form.get('pitches', ''))
        if pitch_count < 0:
            raise ValueError
    except (TypeError, ValueError):
        flash('Pitch count must be a non-negative whole number.', 'danger')
        return _redirect_back()

    try:
        player_id = int(request.form.get('player_id', ''))
    except (TypeError, ValueError):
        flash('A valid pitcher must be selected.', 'danger')
        return _redirect_back()

    player = db.session.query(Player).filter_by(id=player_id, team_id=team_id).first()
    if not player:
        flash('Selected pitcher not found on this team.', 'danger')
        return _redirect_back()

    pitch_date = parse_date(request.form.get('pitch_date'))
    if not pitch_date:
        if game:
            pitch_date = game.date
        else:
            flash('A valid date is required.', 'danger')
            return _redirect_back()

    innings_pitched = None
    pitcher_type = None
    if outing_type == 'Game':
        innings_pitched = _innings_from_form(request.form)
        if innings_pitched is None:
            flash('Game innings must use baseball notation: whole innings plus 0, 1, or 2 outs.', 'danger')
            return _redirect_back()
        pitcher_type = request.form.get('pitcher_type', 'Starter')
        if pitcher_type not in PITCHER_TYPES:
            pitcher_type = 'Starter'

    if game:
        context = game.opponent
    else:
        context = str(request.form.get('opponent') or '').strip()
        if outing_type == 'Game' and not context:
            flash('Opponent is required for a game outing.', 'danger')
            return _redirect_back()
        if not context:
            context = 'Practice' if outing_type == 'Practice' else 'Pitching Lesson'

    new_outing = PitchingOuting(
        date=pitch_date,
        player_id=player_id,
        opponent=context,
        pitches=pitch_count,
        innings=innings_pitched,
        pitcher_type=pitcher_type,
        outing_type=outing_type,
        team_id=team_id,
        game_id=game.id if game else None,
    )
    db.session.add(new_outing)
    db.session.commit()
    flash(f'Pitching workload for "{player.full_name}" added successfully!', 'success')
    socketio.emit('pitching_update', {'message': 'Pitching outing added.'})

    if game:
        return redirect(url_for('gameday.game_management', game_id=game.id, _anchor='pitching'))
    return redirect(url_for('pitching.pitching_page'))


@pitching_bp.route('/edit_pitching/<int:outing_id>', methods=['POST'])
def edit_pitching(outing_id):
    team_id = session.get('team_id')
    outing = db.session.query(PitchingOuting).filter_by(id=outing_id, team_id=team_id).first()
    if not outing:
        flash('Pitching outing not found or you do not have permission to edit it.', 'danger')
        return _redirect_back()

    try:
        pitch_date_str = request.form.get('pitch_date')
        if pitch_date_str:
            parsed_date = parse_date(pitch_date_str)
            if not parsed_date:
                flash('Invalid date format.', 'danger')
                return _redirect_back()
            outing.date = parsed_date

        player_id = request.form.get('player_id')
        if player_id:
            player = db.session.query(Player).filter_by(id=int(player_id), team_id=team_id).first()
            if not player:
                flash('Selected pitcher not found on this team.', 'danger')
                return _redirect_back()
            outing.player_id = player.id

        pitch_count = int(request.form.get('pitches', outing.pitches))
        if pitch_count < 0:
            raise ValueError
        outing.pitches = pitch_count

        # An outing tied to a scheduled game remains a Game outing.
        outing_type = 'Game' if outing.game_id else _outing_type(request.form.get('outing_type', outing.outing_type))
        outing.outing_type = outing_type

        if outing_type == 'Game':
            innings = _innings_from_form(request.form)
            if innings is None:
                flash('Game innings must use whole innings plus 0, 1, or 2 outs.', 'danger')
                return _redirect_back()
            outing.innings = innings
            pitcher_type = request.form.get('pitcher_type', outing.pitcher_type or 'Starter')
            outing.pitcher_type = pitcher_type if pitcher_type in PITCHER_TYPES else 'Starter'
        else:
            # Practice/lesson records are throwing-workload entries, not game stats.
            outing.innings = None
            outing.pitcher_type = None

        if outing.game_id:
            game = db.session.query(Game).filter_by(id=outing.game_id, team_id=team_id).first()
            if game:
                outing.opponent = game.opponent
        else:
            context = str(request.form.get('opponent') or '').strip()
            if outing_type == 'Game' and not context:
                flash('Opponent is required for a game outing.', 'danger')
                return _redirect_back()
            outing.opponent = context or ('Practice' if outing_type == 'Practice' else 'Pitching Lesson')

        db.session.commit()
        player_name = outing.player.full_name if outing.player else 'pitcher'
        flash(f'Successfully updated outing for {player_name}.', 'success')
        socketio.emit('pitching_update', {'message': 'Pitching outing updated.'})
    except (TypeError, ValueError):
        db.session.rollback()
        flash('Pitch count must be a valid non-negative whole number.', 'danger')
    except Exception as exc:
        db.session.rollback()
        flash(f'An error occurred: {exc}', 'danger')

    return _redirect_back()


@pitching_bp.route('/delete_pitching/<int:outing_id>')
def delete_pitching(outing_id):
    outing = db.session.query(PitchingOuting).filter_by(id=outing_id, team_id=session.get('team_id')).first()
    if outing:
        player_name = outing.player.full_name if outing.player else 'An unknown player'
        db.session.delete(outing)
        db.session.commit()
        flash(f'Pitching outing for "{player_name}" removed successfully!', 'success')
        socketio.emit('pitching_update', {'message': 'Pitching outing deleted.'})
    else:
        flash('Pitching outing not found.', 'danger')
    return _redirect_back()


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('auth.login'))
        if 'team_id' not in session:
            flash('Please select a team first.', 'warning')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


@pitching_bp.route('/pitching', methods=['GET'])
@login_required
def pitching_page():
    team_id = session['team_id']
    team = db.session.get(Team, team_id)

    all_players = db.session.query(Player).filter_by(team_id=team_id).all()
    all_outings = db.session.query(PitchingOuting).filter_by(team_id=team_id).options(joinedload(PitchingOuting.player)).all()
    all_targets = db.session.query(PlayerPitchTarget).filter_by(team_id=team_id).all()
    recent_outings = sorted(all_outings, key=lambda o: o.date, reverse=True)[:15]

    rules = get_pitching_rules_for_team(team)
    pitch_count_summary = calculate_pitch_count_summary(
        all_players,
        all_outings,
        rules,
        all_targets=all_targets,
        team_timezone=team.timezone,
    )

    designated_pitchers = {p.id: p for p in all_players if p.pitcher_role != 'Not a Pitcher'}
    players_with_outings = {o.player_id: o.player for o in all_outings if o.player is not None}
    pitchers = list({**designated_pitchers, **players_with_outings}.values())

    return render_template(
        'pitching.html',
        recent_outings=recent_outings,
        pitch_count_summary=pitch_count_summary,
        current_team=team,
        pitchers=pitchers,
        rules=rules,
    )


@pitching_bp.route('/save_player_target', methods=['POST'])
def save_player_target():
    data = request.get_json(silent=True) or {}
    team_id = session.get('team_id')
    player_id = data.get('player_id')
    local_date = data.get('local_date')
    game_id = data.get('game_id')
    target_pitches = data.get('target_pitches')
    reason = data.get('reason')

    if not team_id or not player_id or not local_date:
        return jsonify({'status': 'error', 'message': 'Missing required fields.'}), 400

    player = db.session.query(Player).filter_by(id=int(player_id), team_id=team_id).first()
    if not player:
        return jsonify({'status': 'error', 'message': 'Player not found.'}), 404

    target = db.session.query(PlayerPitchTarget).filter_by(
        player_id=player.id,
        local_date=local_date,
        game_id=game_id,
        team_id=team_id,
    ).first()

    # Blank means clear, matching what the UI promises.
    if target_pitches in (None, ''):
        if target:
            db.session.delete(target)
            db.session.commit()
        return jsonify({'status': 'success', 'cleared': True})

    try:
        target_value = int(target_pitches)
        if target_value < 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'Target pitches must be a non-negative whole number.'}), 400

    if target:
        target.target_pitches = target_value
        target.reason = reason
    else:
        db.session.add(PlayerPitchTarget(
            player_id=player.id,
            target_pitches=target_value,
            local_date=local_date,
            game_id=game_id,
            reason=reason,
            team_id=team_id,
        ))

    db.session.commit()
    return jsonify({'status': 'success'})


@pitching_bp.route('/rules')
def pitching_rules():
    team = db.session.get(Team, session['team_id'])
    rules_for_team = get_pitching_rules_for_team(team)
    return render_template(
        'rules.html',
        current_team=team,
        team=team,
        rules=rules_for_team,
        rule_set_name=rules_for_team.get('rule_set_name', team.pitching_rule_set),
        age_group=team.age_group,
    )
