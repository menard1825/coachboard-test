from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

from db import db
from extensions import socketio
from models import Game, GameRotationEvent, Player, Rotation, Team
from team_game_settings import regulation_innings_for_team, suggested_regulation_innings
from utils import model_to_dict


rotation_templates_bp = Blueprint('rotation_templates', __name__)
PRESET_PREFIX = 'DEFENSE PRESET — '


def _team_context():
    if 'logged_in' not in session:
        return None
    team_id = session.get('team_id')
    if not team_id:
        return None
    return db.session.get(Team, team_id)


def _team_today(team):
    try:
        return datetime.now(ZoneInfo(team.timezone or 'America/Indiana/Indianapolis')).date()
    except Exception:
        return datetime.now().date()


def _positions(team):
    base = ['P', 'C', '1B', '2B', '3B', 'SS']
    outfield = ['LF', 'LCF', 'RCF', 'RF'] if int(team.outfielder_count or 3) == 4 else ['LF', 'CF', 'RF']
    return base + outfield


@rotation_templates_bp.before_app_request
def prepare_regulation_innings_for_game_management():
    """Give new/current pregame rotations the team's regulation inning slots.

    This intentionally does not touch live games, games with live history, or
    historical games. Extra innings remain a live-game concern rather than
    something every pregame plan must include.
    """
    if request.method != 'GET' or request.endpoint != 'gameday.game_management':
        return None

    team = _team_context()
    if not team:
        return None

    try:
        game_id = int((request.view_args or {}).get('game_id'))
    except (TypeError, ValueError):
        return None

    game = db.session.query(Game).filter_by(id=game_id, team_id=team.id).first()
    if not game or game.is_live or game.date.date() < _team_today(team):
        return None

    has_live_history = db.session.query(GameRotationEvent.id).filter_by(
        game_id=game.id,
        team_id=team.id,
        reverted=False,
    ).first()
    if has_live_history:
        return None

    count = regulation_innings_for_team(team)
    rotation = db.session.query(Rotation).filter_by(
        associated_game_id=game.id,
        team_id=team.id,
    ).first()

    if rotation is None:
        db.session.add(Rotation(
            title=f'Rotation for vs {game.opponent}',
            innings={str(number): {} for number in range(1, count + 1)},
            associated_game_id=game.id,
            team_id=team.id,
        ))
        db.session.commit()
        return None

    innings = deepcopy(rotation.innings or {})
    changed = False
    for number in range(1, count + 1):
        key = str(number)
        if key not in innings:
            innings[key] = {}
            changed = True
    if changed:
        rotation.innings = dict(sorted(innings.items(), key=lambda item: float(item[0])))
        db.session.commit()
    return None


def _clean_innings(raw_innings, team, roster_names):
    if not isinstance(raw_innings, dict):
        return None, 'Rotation innings must be an object.'

    allowed_positions = set(_positions(team))
    cleaned = {}

    for raw_inning, raw_alignment in raw_innings.items():
        try:
            inning_number = int(str(raw_inning))
        except (TypeError, ValueError):
            return None, f'Invalid inning: {raw_inning}'
        if inning_number < 1 or inning_number > 20:
            return None, 'Inning numbers must be between 1 and 20.'
        if not isinstance(raw_alignment, dict):
            return None, f'Inning {inning_number} must contain a defensive alignment.'

        alignment = {}
        used_players = set()
        for position in allowed_positions:
            name = str(raw_alignment.get(position) or '').strip()
            if not name:
                continue
            if name not in roster_names:
                return None, f'{name} is not on the active team roster.'
            if name in used_players:
                return None, f'{name} is assigned to more than one position in inning {inning_number}.'
            alignment[position] = name
            used_players.add(name)

        cleaned[str(inning_number)] = alignment

    if not cleaned:
        cleaned = {'1': {}}

    return dict(sorted(cleaned.items(), key=lambda item: int(item[0]))), None


def _first_alignment(raw_innings):
    if not isinstance(raw_innings, dict):
        return {}
    if isinstance(raw_innings.get('1'), dict):
        return deepcopy(raw_innings['1'])
    for key in sorted(raw_innings, key=lambda value: str(value)):
        if isinstance(raw_innings.get(key), dict):
            return deepcopy(raw_innings[key])
    return {}


def _editor_payload(team, rotation=None, template_kind='rotation'):
    is_starting_defense = template_kind == 'starting_defense'
    roster = db.session.query(Player).filter_by(team_id=team.id).order_by(Player.name).all()
    presets = db.session.query(Rotation).filter(
        Rotation.team_id == team.id,
        Rotation.associated_game_id.is_(None),
        Rotation.title.like(f'{PRESET_PREFIX}%'),
    ).order_by(Rotation.title.asc()).all()

    regulation_innings = 1 if is_starting_defense else regulation_innings_for_team(team)
    rotation_data = model_to_dict(rotation) if rotation else {
        'id': None,
        'title': '',
        'innings': {str(i): {} for i in range(1, regulation_innings + 1)},
        'associated_game_id': None,
    }
    if is_starting_defense:
        rotation_data = deepcopy(rotation_data)
        stored_title = str(rotation_data.get('title') or '')
        if stored_title.startswith(PRESET_PREFIX):
            rotation_data['title'] = stored_title[len(PRESET_PREFIX):].strip()
        rotation_data['innings'] = {'1': _first_alignment(rotation_data.get('innings'))}

    return {
        'rotation': rotation_data,
        'roster': [model_to_dict(player) for player in roster],
        'outfielder_count': int(team.outfielder_count or 3),
        'defense_presets': [model_to_dict(preset) for preset in presets],
        'preset_prefix': PRESET_PREFIX,
        'regulation_innings': regulation_innings,
        'regulation_innings_override': team.regulation_innings,
        'suggested_regulation_innings': suggested_regulation_innings(team.age_group),
        'age_group': team.age_group,
        'template_kind': template_kind,
        'save_url': '/api/starting-defense-template/save' if is_starting_defense else '/api/rotation-template/save',
        'edit_url_base': '/starting-defense-template' if is_starting_defense else '/rotation-template',
        'save_button_label': 'Save Starting Defense' if is_starting_defense else 'Save Template',
    }


@rotation_templates_bp.route('/api/team-game-settings')
def team_game_settings_api():
    team = _team_context()
    if not team:
        return jsonify({'status': 'error', 'message': 'Unauthorized.'}), 401
    return jsonify({
        'status': 'success',
        'age_group': team.age_group,
        'regulation_innings': regulation_innings_for_team(team),
        'regulation_innings_override': team.regulation_innings,
        'suggested_regulation_innings': suggested_regulation_innings(team.age_group),
    })


@rotation_templates_bp.route('/admin/settings/regulation-innings', methods=['POST'])
def update_regulation_innings():
    team = _team_context()
    if not team:
        return redirect(url_for('auth.login'))
    if session.get('role') not in {'Head Coach', 'Super Admin'}:
        flash('You must be a Head Coach or Super Admin to change team game settings.', 'danger')
        return redirect(url_for('home'))

    raw_value = str(request.form.get('regulation_innings') or '').strip()
    if not raw_value:
        team.regulation_innings = None
        message = f'Regulation innings set to Auto ({suggested_regulation_innings(team.age_group)} for {team.age_group}).'
    else:
        try:
            value = int(raw_value)
        except ValueError:
            flash('Regulation innings must be a whole number.', 'danger')
            return redirect(url_for('admin.admin_settings'))
        if value < 3 or value > 12:
            flash('Regulation innings must be between 3 and 12.', 'danger')
            return redirect(url_for('admin.admin_settings'))
        team.regulation_innings = value
        message = f'Regulation innings set to {value}.'

    db.session.commit()
    socketio.emit('data_updated', {'message': 'Team regulation innings updated.'})
    flash(message, 'success')
    return redirect(url_for('admin.admin_settings'))


@rotation_templates_bp.route('/rotation-template/new')
def new_rotation_template():
    team = _team_context()
    if not team:
        return redirect(url_for('auth.login'))
    return render_template(
        'rotation_template_editor.html',
        current_team=team,
        editor_data=_editor_payload(team),
    )


@rotation_templates_bp.route('/rotation-template/<int:rotation_id>')
def edit_rotation_template(rotation_id):
    team = _team_context()
    if not team:
        return redirect(url_for('auth.login'))

    rotation = db.session.query(Rotation).filter_by(
        id=rotation_id,
        team_id=team.id,
        associated_game_id=None,
    ).first()
    if not rotation or str(rotation.title or '').startswith(PRESET_PREFIX):
        return redirect(url_for('home', _anchor='rotations'))

    return render_template(
        'rotation_template_editor.html',
        current_team=team,
        editor_data=_editor_payload(team, rotation),
    )


@rotation_templates_bp.route('/starting-defense-template/new')
def new_starting_defense_template():
    team = _team_context()
    if not team:
        return redirect(url_for('auth.login'))
    return render_template(
        'rotation_template_editor.html',
        current_team=team,
        editor_data=_editor_payload(team, template_kind='starting_defense'),
    )


@rotation_templates_bp.route('/starting-defense-template/<int:rotation_id>')
def edit_starting_defense_template(rotation_id):
    team = _team_context()
    if not team:
        return redirect(url_for('auth.login'))

    rotation = db.session.query(Rotation).filter_by(
        id=rotation_id,
        team_id=team.id,
        associated_game_id=None,
    ).first()
    if not rotation or not str(rotation.title or '').startswith(PRESET_PREFIX):
        return redirect(url_for('home', _anchor='rotations'))

    return render_template(
        'rotation_template_editor.html',
        current_team=team,
        editor_data=_editor_payload(team, rotation, template_kind='starting_defense'),
    )


@rotation_templates_bp.route('/api/rotation-template/save', methods=['POST'])
def save_rotation_template():
    team = _team_context()
    if not team:
        return jsonify({'status': 'error', 'message': 'Unauthorized.'}), 401

    data = request.get_json(silent=True) or {}
    title = str(data.get('title') or '').strip()
    if not title:
        return jsonify({'status': 'error', 'message': 'Template name is required.'}), 400
    if title.startswith(PRESET_PREFIX):
        return jsonify({'status': 'error', 'message': 'That name is reserved for Defense Presets.'}), 400

    roster_names = {
        player.name
        for player in db.session.query(Player).filter_by(team_id=team.id).all()
    }
    innings, error = _clean_innings(data.get('innings'), team, roster_names)
    if error:
        return jsonify({'status': 'error', 'message': error}), 400

    regulation_innings = regulation_innings_for_team(team)
    for inning_number in range(1, regulation_innings + 1):
        innings.setdefault(str(inning_number), {})
    innings = dict(sorted(innings.items(), key=lambda item: int(item[0])))

    rotation_id = data.get('id')
    rotation = None
    if rotation_id not in (None, ''):
        try:
            rotation_id = int(rotation_id)
        except (TypeError, ValueError):
            return jsonify({'status': 'error', 'message': 'Invalid template ID.'}), 400
        rotation = db.session.query(Rotation).filter_by(
            id=rotation_id,
            team_id=team.id,
            associated_game_id=None,
        ).first()
        if not rotation or str(rotation.title or '').startswith(PRESET_PREFIX):
            return jsonify({'status': 'error', 'message': 'Rotation template not found.'}), 404

    duplicate = db.session.query(Rotation).filter(
        Rotation.team_id == team.id,
        Rotation.associated_game_id.is_(None),
        Rotation.title == title,
    ).first()
    if duplicate and (not rotation or duplicate.id != rotation.id):
        return jsonify({'status': 'error', 'message': f'A rotation template named "{title}" already exists.'}), 409

    if rotation is None:
        rotation = Rotation(
            title=title,
            innings=deepcopy(innings),
            associated_game_id=None,
            team_id=team.id,
        )
        db.session.add(rotation)
    else:
        rotation.title = title
        rotation.innings = deepcopy(innings)
        rotation.associated_game_id = None

    db.session.commit()
    socketio.emit('rotation_save', {'rotation': model_to_dict(rotation)})
    socketio.emit('data_updated', {'message': 'Rotation template saved.'})

    return jsonify({
        'status': 'success',
        'message': 'Rotation template saved.',
        'id': rotation.id,
        'rotation': model_to_dict(rotation),
        'regulation_innings': regulation_innings,
    })


@rotation_templates_bp.route('/api/starting-defense-template/save', methods=['POST'])
def save_starting_defense_template():
    team = _team_context()
    if not team:
        return jsonify({'status': 'error', 'message': 'Unauthorized.'}), 401

    data = request.get_json(silent=True) or {}
    display_title = str(data.get('title') or '').strip()
    if not display_title:
        return jsonify({'status': 'error', 'message': 'Starting defense name is required.'}), 400
    if display_title.startswith(PRESET_PREFIX):
        display_title = display_title[len(PRESET_PREFIX):].strip()
    if not display_title:
        return jsonify({'status': 'error', 'message': 'Starting defense name is required.'}), 400

    roster_names = {
        player.name
        for player in db.session.query(Player).filter_by(team_id=team.id).all()
    }
    innings, error = _clean_innings(data.get('innings'), team, roster_names)
    if error:
        return jsonify({'status': 'error', 'message': error}), 400

    alignment = _first_alignment(innings)
    missing = [position for position in _positions(team) if position != 'P' and not alignment.get(position)]
    if missing:
        return jsonify({
            'status': 'error',
            'message': f"Fill {', '.join(missing)} before saving. Pitcher may remain open.",
        }), 400

    stored_title = PRESET_PREFIX + display_title
    rotation_id = data.get('id')
    rotation = None
    if rotation_id not in (None, ''):
        try:
            rotation_id = int(rotation_id)
        except (TypeError, ValueError):
            return jsonify({'status': 'error', 'message': 'Invalid starting defense ID.'}), 400
        rotation = db.session.query(Rotation).filter_by(
            id=rotation_id,
            team_id=team.id,
            associated_game_id=None,
        ).first()
        if not rotation or not str(rotation.title or '').startswith(PRESET_PREFIX):
            return jsonify({'status': 'error', 'message': 'Starting defense template not found.'}), 404

    duplicate = db.session.query(Rotation).filter(
        Rotation.team_id == team.id,
        Rotation.associated_game_id.is_(None),
        Rotation.title == stored_title,
    ).first()
    if duplicate and (not rotation or duplicate.id != rotation.id):
        return jsonify({
            'status': 'error',
            'message': f'A starting defense named "{display_title}" already exists.',
        }), 409

    if rotation is None:
        rotation = Rotation(
            title=stored_title,
            innings={'1': alignment},
            associated_game_id=None,
            team_id=team.id,
        )
        db.session.add(rotation)
    else:
        rotation.title = stored_title
        rotation.innings = {'1': alignment}
        rotation.associated_game_id = None

    db.session.commit()
    socketio.emit('rotation_save', {'rotation': model_to_dict(rotation)})
    socketio.emit('data_updated', {'message': 'Starting defense template saved.'})

    return jsonify({
        'status': 'success',
        'message': 'Starting defense template saved.',
        'id': rotation.id,
        'rotation': model_to_dict(rotation),
        'display_title': display_title,
        'regulation_innings': 1,
    })
