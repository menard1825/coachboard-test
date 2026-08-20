from flask import Blueprint, jsonify, request, session

from db import db
from models import Team, Player, PitchingOuting, PlayerPitchTarget
from utils import PITCHING_RULES, calculate_pitch_count_summary, get_pitching_rules_for_team
from pitching_rule_presets import install_additional_pitching_rules


install_additional_pitching_rules(PITCHING_RULES)

pitching_policy_bp = Blueprint('pitching_policy', __name__)

NO_COMPETITION_RULE = 'No Competition Rule Selected'
ARM_CARE_OPTIONS = ('MLB Pitch Smart', 'Off')


class TeamPitchingSetting(db.Model):
    __tablename__ = 'team_pitching_settings'

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id', ondelete='CASCADE'), nullable=False, unique=True, index=True)
    competition_default_rule = db.Column(db.String(64), nullable=True)
    arm_care_rule_set = db.Column(db.String(64), nullable=True)


def _team():
    team_id = session.get('team_id')
    if not team_id:
        return None
    return db.session.get(Team, team_id)


def get_team_pitching_setting(team, create=False):
    setting = db.session.query(TeamPitchingSetting).filter_by(team_id=team.id).first()
    if not setting and create:
        setting = TeamPitchingSetting(
            team_id=team.id,
            competition_default_rule=None,
            arm_care_rule_set='MLB Pitch Smart',
        )
        db.session.add(setting)
    return setting


def competition_default_name(team):
    setting = get_team_pitching_setting(team)
    if setting:
        return setting.competition_default_rule or None
    # Before the migration/settings are touched, preserve legacy behavior.
    return getattr(team, 'pitching_rule_set', None) or None


def arm_care_name(team):
    setting = get_team_pitching_setting(team)
    if setting:
        return setting.arm_care_rule_set or 'Off'
    return 'MLB Pitch Smart'


def competition_rules_for_team(team):
    selected = competition_default_name(team)
    if not selected:
        return {
            'rule_type': 'unsupported',
            'rule_set_name': NO_COMPETITION_RULE,
            'configured_rule_set_name': None,
            'age_group': getattr(team, 'age_group', 'default') or 'default',
            'source_note': 'No default competition rule is selected. Choose the tournament or league rule from Game Planning when it applies.',
        }

    original = getattr(team, 'pitching_rule_set', None)
    team.pitching_rule_set = selected
    try:
        return get_pitching_rules_for_team(team)
    finally:
        team.pitching_rule_set = original


def policy_payload(team):
    setting = get_team_pitching_setting(team)
    return {
        'competition_default': competition_default_name(team),
        'arm_care_rule_set': arm_care_name(team),
        'competition_options': list(PITCHING_RULES.keys()),
        'arm_care_options': list(ARM_CARE_OPTIONS),
        'has_saved_policy': bool(setting),
    }


@pitching_policy_bp.route('/api/pitching-policy', methods=['GET', 'POST'])
def pitching_policy():
    team = _team()
    if not team or not session.get('logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized.'}), 401

    if request.method == 'POST':
        if session.get('role') not in {'Head Coach', 'Super Admin'}:
            return jsonify({'status': 'error', 'message': 'Only a Head Coach or Super Admin can change team pitching policy.'}), 403

        data = request.get_json(silent=True) or {}
        competition = str(data.get('competition_default') or '').strip() or None
        arm_care = str(data.get('arm_care_rule_set') or '').strip() or 'Off'

        if competition and competition not in PITCHING_RULES:
            return jsonify({'status': 'error', 'message': 'Unsupported competition rule set.'}), 400
        if arm_care not in ARM_CARE_OPTIONS:
            return jsonify({'status': 'error', 'message': 'Unsupported arm-care setting.'}), 400

        setting = get_team_pitching_setting(team, create=True)
        setting.competition_default_rule = competition
        setting.arm_care_rule_set = arm_care
        db.session.commit()

    return jsonify({'status': 'success', **policy_payload(team)})


@pitching_policy_bp.route('/api/pitching-policy/arm-care-summary')
def arm_care_summary():
    team = _team()
    if not team or not session.get('logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized.'}), 401

    selected = arm_care_name(team)
    if selected == 'Off':
        return jsonify({'status': 'success', 'enabled': False, 'rule_set': 'Off', 'players': []})

    # Arm-care guidance is intentionally independent of tournament eligibility.
    # Pitch Smart guidance uses game pitches; practice/lesson throws remain visible
    # as workload context rather than being treated as official game pitches.
    original = getattr(team, 'pitching_rule_set', None)
    team.pitching_rule_set = selected
    try:
        rules = get_pitching_rules_for_team(team)
    finally:
        team.pitching_rule_set = original

    players = db.session.query(Player).filter_by(team_id=team.id).all()
    outings = db.session.query(PitchingOuting).filter_by(team_id=team.id).all()
    targets = db.session.query(PlayerPitchTarget).filter_by(team_id=team.id).all()
    summary = calculate_pitch_count_summary(
        players,
        outings,
        rules,
        all_targets=targets,
        team_timezone=team.timezone,
    )

    rows = []
    for player in players:
        item = summary.get(player.name)
        if not item:
            continue
        rows.append({
            'player_id': player.id,
            'player_name': player.name,
            'status': item.get('status'),
            'status_detail': item.get('status_detail'),
            'next_available': item.get('next_available'),
            'game_pitches_today': item.get('official_daily_pitches'),
            'game_pitches_7_day': item.get('official_7_day_pitches'),
            'workload_today': item.get('workload_daily_pitches'),
            'workload_7_day': item.get('workload_7_day_pitches'),
            'max_daily': item.get('max_daily'),
        })

    return jsonify({
        'status': 'success',
        'enabled': True,
        'rule_set': selected,
        'note': 'Arm-care guidance is separate from tournament eligibility. Pitch Smart thresholds use game pitches; total throwing workload is shown alongside them.',
        'players': rows,
    })
