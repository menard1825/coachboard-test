from flask import Blueprint, jsonify, redirect, request, session, url_for
from sqlalchemy.orm import joinedload

from db import db
from models import (
    Game,
    PitchingOuting,
    Player,
    PlayerPitchTarget,
    Team,
    TeamMembership,
    User,
)
from utils import PITCHING_RULES, calculate_pitch_count_summary


fair_play_bp = Blueprint('fair_play', __name__)

VALID_MODES = {'off', 'track', 'rules'}
VALID_INFIELD_POSITIONS = ('P', 'C', '1B', '2B', '3B', 'SS')
DEFAULT_INFIELD_POSITIONS = ('1B', '2B', '3B', 'SS')
EDIT_ROLES = {'Head Coach', 'Super Admin'}
ARM_CARE_RULE_OPTIONS = ('MLB Pitch Smart',)


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


class TeamPitchingSettings(db.Model):
    """Separate event eligibility rules from the team's arm-care preference."""

    __tablename__ = 'team_pitching_settings'

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(
        db.Integer,
        db.ForeignKey('teams.id', ondelete='CASCADE'),
        nullable=False,
        unique=True,
        index=True,
    )
    competition_default_rule = db.Column(db.String(64), nullable=True)
    arm_care_rule_set = db.Column(db.String(64), nullable=True, default='MLB Pitch Smart')


def _current_team():
    if not session.get('logged_in'):
        return None
    team_id = session.get('team_id')
    if not team_id:
        return None
    return db.session.get(Team, team_id)


def _current_membership():
    username = session.get('username')
    team_id = session.get('team_id')
    if not username or not team_id:
        return None
    user = db.session.query(User).filter(db.func.lower(User.username) == str(username).lower()).first()
    if not user:
        return None
    return db.session.query(TeamMembership).filter_by(user_id=user.id, team_id=team_id).first()


def _can_edit():
    membership = _current_membership()
    return bool(membership and membership.role in EDIT_ROLES)


def _settings_row(team_id):
    return db.session.query(TeamFairPlaySettings).filter_by(team_id=team_id).first()


def _pitching_row(team_id):
    return db.session.query(TeamPitchingSettings).filter_by(team_id=team_id).first()


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


def _serialize_pitching(row):
    competition_default = row.competition_default_rule if row else None
    arm_care = row.arm_care_rule_set if row else 'MLB Pitch Smart'
    if competition_default not in PITCHING_RULES:
        competition_default = None
    if arm_care not in ARM_CARE_RULE_OPTIONS:
        arm_care = None
    return {
        'competition_default_rule': competition_default,
        'arm_care_rule_set': arm_care,
    }


def pitching_preferences_for_team(team):
    """Return normalized pitching preferences for a Team instance."""
    return _serialize_pitching(_pitching_row(team.id))


def pitching_rules_for_name(team, rule_name):
    """Build an age-specific rules dict without changing the Team row."""
    if not rule_name or rule_name not in PITCHING_RULES:
        return {
            'rule_type': 'unsupported',
            'rule_set_name': 'Rules Not Selected',
            'configured_rule_set_name': None,
            'age_group': team.age_group,
            'source_note': 'No competition pitching rules are selected. Choose the tournament or league rules for each game or set an optional team default.',
            'competition_unselected': True,
        }

    rule_set = PITCHING_RULES[rule_name]
    age_group = team.age_group or 'default'
    effective_age = age_group
    source_note = None

    if rule_name == 'MLB Pitch Smart' and age_group in {'4U', '5U', '6U'}:
        effective_age = '7U'
        source_note = 'MLB Pitch Smart publishes its first pitch-count table at ages 7–8; using that guidance for this younger team setting.'
    if rule_name == 'USSSA' and age_group not in rule_set:
        source_note = f'USSSA youth limits for {age_group} are not explicitly configured; verify the event rules before relying on eligibility.'

    rules = dict(rule_set.get(effective_age, rule_set.get('default', {})))
    rules['rule_set_name'] = rule_name
    rules['configured_rule_set_name'] = rule_name
    rules['age_group'] = age_group
    rules['source_note'] = source_note or rules.get('rule_note')
    rules['competition_unselected'] = False
    return rules


def _parse_bounded_int(value, field_name, minimum, maximum):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f'{field_name} must be a number.')
    if parsed < minimum or parsed > maximum:
        raise ValueError(f'{field_name} must be between {minimum} and {maximum}.')
    return parsed


@fair_play_bp.before_app_request
def redirect_rules_page_when_no_default():
    """Avoid rendering the legacy single-rule page when no competition default exists."""
    if request.endpoint != 'pitching.pitching_rules':
        return None
    team = _current_team()
    if not team:
        return None
    if pitching_preferences_for_team(team)['competition_default_rule'] is None:
        return redirect(url_for('admin.admin_settings', _anchor='pitching-rules-settings'))
    return None


@fair_play_bp.route('/api/fair-play/settings', methods=['GET'])
def get_fair_play_settings():
    team = _current_team()
    if not team:
        return jsonify({'status': 'error', 'message': 'Sign in and select a team first.'}), 401

    return jsonify({
        'status': 'success',
        'team_id': team.id,
        'team_name': team.team_name,
        'can_edit': _can_edit(),
        'settings': _serialize(_settings_row(team.id)),
    })


@fair_play_bp.route('/api/fair-play/settings', methods=['POST'])
def update_fair_play_settings():
    team = _current_team()
    if not team:
        return jsonify({'status': 'error', 'message': 'Sign in and select a team first.'}), 401
    if not _can_edit():
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


@fair_play_bp.route('/api/pitching-preferences/settings', methods=['GET'])
def get_pitching_preferences():
    team = _current_team()
    if not team:
        return jsonify({'status': 'error', 'message': 'Sign in and select a team first.'}), 401

    return jsonify({
        'status': 'success',
        'team_id': team.id,
        'team_name': team.team_name,
        'age_group': team.age_group,
        'can_edit': _can_edit(),
        'settings': pitching_preferences_for_team(team),
        'competition_options': list(PITCHING_RULES.keys()),
        'arm_care_options': list(ARM_CARE_RULE_OPTIONS),
    })


@fair_play_bp.route('/api/pitching-preferences/settings', methods=['POST'])
def update_pitching_preferences():
    team = _current_team()
    if not team:
        return jsonify({'status': 'error', 'message': 'Sign in and select a team first.'}), 401
    if not _can_edit():
        return jsonify({'status': 'error', 'message': 'Only a Head Coach or Super Admin can change team pitching settings.'}), 403

    payload = request.get_json(silent=True)
    if payload is None:
        payload = request.form.to_dict(flat=True)

    raw_competition = payload.get('competition_default_rule')
    competition_default = str(raw_competition or '').strip()
    if competition_default.lower() in {'', 'none', 'off', 'no default'}:
        competition_default = None
    elif competition_default not in PITCHING_RULES:
        return jsonify({'status': 'error', 'message': 'Choose a supported competition pitching rule set.'}), 400

    raw_arm_care = payload.get('arm_care_rule_set')
    arm_care = str(raw_arm_care or '').strip()
    if arm_care.lower() in {'', 'none', 'off'}:
        arm_care = None
    elif arm_care not in ARM_CARE_RULE_OPTIONS:
        return jsonify({'status': 'error', 'message': 'Choose MLB Pitch Smart arm-care guidance or turn arm-care guidance off.'}), 400

    row = _pitching_row(team.id)
    if not row:
        row = TeamPitchingSettings(team_id=team.id)
        db.session.add(row)
    row.competition_default_rule = competition_default
    row.arm_care_rule_set = arm_care
    db.session.commit()

    return jsonify({
        'status': 'success',
        'message': 'Pitching settings saved.',
        'settings': _serialize_pitching(row),
    })


@fair_play_bp.route('/api/pitching-preferences/arm-care-summary', methods=['GET'])
def arm_care_summary():
    team = _current_team()
    if not team:
        return jsonify({'status': 'error', 'message': 'Sign in and select a team first.'}), 401

    preferences = pitching_preferences_for_team(team)
    arm_care_rule = preferences['arm_care_rule_set']
    if not arm_care_rule:
        return jsonify({
            'status': 'success',
            'enabled': False,
            'rule_set': None,
            'players': {},
        })

    game = None
    game_id = request.args.get('game_id')
    if game_id not in (None, ''):
        try:
            normalized_game_id = int(game_id)
        except (TypeError, ValueError):
            return jsonify({'status': 'error', 'message': 'Game must be valid.'}), 400
        game = db.session.query(Game).filter_by(id=normalized_game_id, team_id=team.id).first()
        if not game:
            return jsonify({'status': 'error', 'message': 'Game not found.'}), 404

    roster = db.session.query(Player).filter_by(team_id=team.id).order_by(Player.name).all()
    all_outings = db.session.query(PitchingOuting).options(joinedload(PitchingOuting.player)).filter_by(team_id=team.id).all()
    all_targets = db.session.query(PlayerPitchTarget).filter_by(team_id=team.id).all()
    rules = pitching_rules_for_name(team, arm_care_rule)
    summary = calculate_pitch_count_summary(
        roster,
        all_outings,
        rules,
        target_date=game.date if game else None,
        all_targets=all_targets,
        team_timezone=team.timezone,
        current_game_id=game.id if game else None,
    )

    outing_player_ids = {outing.player_id for outing in all_outings}
    players = {}
    for player in roster:
        if player.pitcher_role == 'Not a Pitcher' and player.id not in outing_player_ids:
            continue
        item = summary.get(player.name) or {}
        players[player.name] = {
            'id': player.id,
            'status': item.get('status'),
            'status_detail': item.get('status_detail'),
            'next_available': item.get('next_available'),
            'game_pitches_today': item.get('official_daily_pitches'),
            'game_pitches_7_day': item.get('official_7_day_pitches'),
            'workload_today': item.get('workload_daily_pitches'),
            'workload_7_day': item.get('workload_7_day_pitches'),
            'max_daily': item.get('max_daily'),
            'pitches_remaining_today': item.get('pitches_remaining_today'),
        }

    return jsonify({
        'status': 'success',
        'enabled': True,
        'rule_set': arm_care_rule,
        'players': players,
    })
