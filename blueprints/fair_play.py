from flask import Blueprint, jsonify, request, session

from db import db
from models import Team


fair_play_bp = Blueprint('fair_play', __name__)

VALID_MODES = {'off', 'track', 'rules'}
VALID_INFIELD_POSITIONS = ('P', 'C', '1B', '2B', '3B', 'SS')
DEFAULT_INFIELD_POSITIONS = ('1B', '2B', '3B', 'SS')
EDIT_ROLES = {'Head Coach', 'Super Admin'}


class TeamFairPlaySettings(db.Model):
    """Optional playing-time assistance preferences scoped to one team."""

    __tablename__ = 'team_fair_play_settings'

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(
        db.Integer,
        db.ForeignKey('teams.id', ondelete='CASCADE'),
        nullable=False,
        unique=True,
        index=True,
    )
    mode = db.Column(db.String(20), nullable=False, default='off')
    min_infield_innings = db.Column(db.Integer, nullable=False, default=1)
    max_consecutive_bench = db.Column(db.Integer, nullable=False, default=1)
    infield_positions = db.Column(db.String(64), nullable=False, default='1B,2B,3B,SS')


def _current_team():
    if not session.get('logged_in'):
        return None
    team_id = session.get('team_id')
    if not team_id:
        return None
    return db.session.get(Team, team_id)


def _settings_row(team_id):
    return db.session.query(TeamFairPlaySettings).filter_by(team_id=team_id).first()


def _positions_from_row(row):
    if not row or not row.infield_positions:
        return list(DEFAULT_INFIELD_POSITIONS)
    positions = []
    for raw in row.infield_positions.split(','):
        pos = raw.strip().upper()
        if pos in VALID_INFIELD_POSITIONS and pos not in positions:
            positions.append(pos)
    return positions or list(DEFAULT_INFIELD_POSITIONS)


def _serialize(row):
    if not row:
        return {
            'mode': 'off',
            'min_infield_innings': 1,
            'max_consecutive_bench': 1,
            'infield_positions': list(DEFAULT_INFIELD_POSITIONS),
        }
    return {
        'mode': row.mode if row.mode in VALID_MODES else 'off',
        'min_infield_innings': row.min_infield_innings,
        'max_consecutive_bench': row.max_consecutive_bench,
        'infield_positions': _positions_from_row(row),
    }


def _parse_bounded_int(value, field_name, minimum, maximum):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f'{field_name} must be a number.')
    if parsed < minimum or parsed > maximum:
        raise ValueError(f'{field_name} must be between {minimum} and {maximum}.')
    return parsed


@fair_play_bp.route('/api/fair-play/settings', methods=['GET'])
def get_fair_play_settings():
    team = _current_team()
    if not team:
        return jsonify({'status': 'error', 'message': 'Sign in and select a team first.'}), 401

    return jsonify({
        'status': 'success',
        'team_id': team.id,
        'team_name': team.team_name,
        'can_edit': session.get('role') in EDIT_ROLES,
        'settings': _serialize(_settings_row(team.id)),
    })


@fair_play_bp.route('/api/fair-play/settings', methods=['POST'])
def update_fair_play_settings():
    team = _current_team()
    if not team:
        return jsonify({'status': 'error', 'message': 'Sign in and select a team first.'}), 401
    if session.get('role') not in EDIT_ROLES:
        return jsonify({'status': 'error', 'message': 'Only a Head Coach or Super Admin can change team playing-time settings.'}), 403

    payload = request.get_json(silent=True)
    if payload is None:
        payload = request.form.to_dict(flat=True)

    mode = str(payload.get('mode', 'off')).strip().lower()
    if mode not in VALID_MODES:
        return jsonify({'status': 'error', 'message': 'Choose Off, Track Only, or Fair Play Rules.'}), 400

    try:
        min_infield = _parse_bounded_int(
            payload.get('min_infield_innings', 1),
            'Minimum infield innings',
            0,
            12,
        )
        max_bench = _parse_bounded_int(
            payload.get('max_consecutive_bench', 1),
            'Maximum consecutive bench innings',
            0,
            6,
        )
    except ValueError as exc:
        return jsonify({'status': 'error', 'message': str(exc)}), 400

    raw_positions = payload.get('infield_positions', list(DEFAULT_INFIELD_POSITIONS))
    if isinstance(raw_positions, str):
        raw_positions = raw_positions.split(',')
    if not isinstance(raw_positions, list):
        return jsonify({'status': 'error', 'message': 'Infield positions must be a list.'}), 400

    positions = []
    invalid_positions = []
    for raw in raw_positions:
        pos = str(raw).strip().upper()
        if not pos:
            continue
        if pos not in VALID_INFIELD_POSITIONS:
            invalid_positions.append(pos)
            continue
        if pos not in positions:
            positions.append(pos)

    if invalid_positions:
        return jsonify({
            'status': 'error',
            'message': f"Unsupported position: {', '.join(invalid_positions)}.",
        }), 400
    if mode == 'rules' and min_infield > 0 and not positions:
        return jsonify({'status': 'error', 'message': 'Choose at least one position that counts as infield.'}), 400

    row = _settings_row(team.id)
    if not row:
        row = TeamFairPlaySettings(team_id=team.id)
        db.session.add(row)

    row.mode = mode
    row.min_infield_innings = min_infield
    row.max_consecutive_bench = max_bench
    row.infield_positions = ','.join(positions)
    db.session.commit()

    return jsonify({
        'status': 'success',
        'message': 'Playing-time settings saved.',
        'settings': _serialize(row),
    })
