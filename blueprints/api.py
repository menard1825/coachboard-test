from flask import Blueprint, jsonify, session
from db import db
from models import User, Team, Player, Lineup, PitchingOuting, ScoutedPlayer, Rotation, Game, CollaborationNote, PracticePlan, PlayerDevelopmentFocus, Sign, PlayerGameAbsence, PlayerPracticeAbsence
from blueprints.auth import get_player_order_as_list
from utils import model_to_dict, pitching_outing_to_dict, get_pitching_rules_for_team, calculate_pitch_count_summary, calculate_cumulative_pitching_stats
from sqlalchemy.orm import joinedload
from sqlalchemy import func
from functools import wraps
from datetime import datetime

api_bp = Blueprint('api', __name__, url_prefix='/api')

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function

@api_bp.route('/session_data')
@login_required
def get_session_data():
    user = db.session.query(User).filter_by(username=session['username']).first()
    team_id = session.get('team_id')
    team = db.session.get(Team, team_id) if team_id else None

    if not user or not team:
        return jsonify({"error": "User or team not found"}), 404

    from models import TeamMembership
    membership = db.session.query(TeamMembership).filter_by(user_id=user.id, team_id=team_id).first()

    return jsonify({
        'session': {
            'username': session.get('username'),
            'role': membership.role if membership else session.get('role'),
            'outfielder_count': team.outfielder_count
        },
        'player_order': get_player_order_as_list(membership.player_order) if membership else [],
    })

@api_bp.route('/roster')
@login_required
def get_roster():
    team_id = session.get('team_id')
    if not team_id:
        return jsonify({"error": "Team not found"}), 404

    roster_db = db.session.query(Player).filter_by(team_id=team_id).all()
    return jsonify([model_to_dict(p) for p in roster_db])

@api_bp.route('/lineups')
@login_required
def get_lineups():
    team_id = session.get('team_id')
    if not team_id:
        return jsonify({"error": "Team not found"}), 404

    lineups_db = db.session.query(Lineup).filter_by(team_id=team_id).all()
    return jsonify([model_to_dict(l) for l in lineups_db])

@api_bp.route('/pitching_data')
@login_required
def get_pitching_data():
    team_id = session.get('team_id')
    if not team_id:
        return jsonify({"error": "Team not found"}), 404

    team = db.session.get(Team, team_id)
    roster_db = db.session.query(Player).filter_by(team_id=team_id).all()
    pitching_outings_db = db.session.query(PitchingOuting).options(joinedload(PitchingOuting.player)).filter_by(team_id=team_id).all()

    from models import PlayerPitchTarget
    all_targets = db.session.query(PlayerPitchTarget).filter_by(team_id=team_id).all()

    rules = get_pitching_rules_for_team(team)
    pitch_count_summary = calculate_pitch_count_summary(roster_db, pitching_outings_db, rules, all_targets=all_targets, team_timezone=team.timezone)

    return jsonify({
        'pitching': [pitching_outing_to_dict(po) for po in pitching_outings_db],
        'pitch_count_summary': pitch_count_summary
    })

@api_bp.route('/scouting_list')
@login_required
def get_scouting_list():
    team_id = session.get('team_id')
    if not team_id:
        return jsonify({"error": "Team not found"}), 404

    scouted_players = db.session.query(ScoutedPlayer).filter_by(team_id=team_id).all()

    return jsonify({
        'targets': [model_to_dict(sp) for sp in scouted_players if sp.list_type == 'targets'],
        'committed': [model_to_dict(sp) for sp in scouted_players if sp.list_type == 'committed'],
        'not_interested': [model_to_dict(sp) for sp in scouted_players if sp.list_type == 'not_interested']
    })

@api_bp.route('/rotations')
@login_required
def get_rotations():
    team_id = session.get('team_id')
    if not team_id:
        return jsonify({"error": "Team not found"}), 404

    rotations_db = db.session.query(Rotation).filter_by(team_id=team_id).all()
    return jsonify([model_to_dict(r) for r in rotations_db])

@api_bp.route('/games')
@login_required
def get_games():
    team_id = session.get('team_id')
    if not team_id:
        return jsonify({"error": "Team not found"}), 404

    games_db = db.session.query(Game).filter_by(team_id=team_id).all()
    return jsonify([model_to_dict(g) for g in games_db])

@api_bp.route('/collaboration_notes')
@login_required
def get_collaboration_notes():
    team_id = session.get('team_id')
    if not team_id:
        return jsonify({"error": "Team not found"}), 404

    collaboration_notes = db.session.query(CollaborationNote).filter_by(team_id=team_id).all()

    return jsonify({
        'team_notes': [model_to_dict(cn) for cn in collaboration_notes if cn.note_type == 'team_notes'],
        'player_notes': [model_to_dict(cn) for cn in collaboration_notes if cn.note_type == 'player_notes']
    })

@api_bp.route('/practice_plans')
@login_required
def get_practice_plans():
    team_id = session.get('team_id')
    if not team_id:
        return jsonify({"error": "Team not found"}), 404

    practice_plans_q = db.session.query(PracticePlan).filter_by(team_id=team_id).options(joinedload(PracticePlan.tasks), joinedload(PracticePlan.absences)).all()

    practice_plans_list = []
    for p in practice_plans_q:
        plan_dict = model_to_dict(p)
        plan_dict['tasks'] = [model_to_dict(t) for t in p.tasks]
        plan_dict['absent_player_ids'] = [a.player_id for a in p.absences]
        practice_plans_list.append(plan_dict)

    return jsonify(practice_plans_list)

@api_bp.route('/player_development')
@login_required
def get_player_development():
    team_id = session.get('team_id')
    if not team_id:
        return jsonify({"error": "Team not found"}), 404

    roster_db = db.session.query(Player).filter_by(team_id=team_id).all()
    player_dev_focuses = db.session.query(PlayerDevelopmentFocus).filter_by(team_id=team_id).all()

    player_dev_by_name = {p.name: [] for p in roster_db}
    player_id_to_name = {p.id: p.name for p in roster_db}

    for focus in player_dev_focuses:
        player_name = player_id_to_name.get(focus.player_id)
        if player_name:
            focus_dict = model_to_dict(focus)
            focus_dict.update({
                'type': 'Development',
                'subtype': focus.skill_type.capitalize(),
                'text': focus.focus,
                'date': focus.created_date.strftime('%Y-%m-%d')
            })
            player_dev_by_name[player_name].append(focus_dict)

    return jsonify(player_dev_by_name)

@api_bp.route('/signs')
@login_required
def get_signs():
    team_id = session.get('team_id')
    if not team_id:
        return jsonify({"error": "Team not found"}), 404

    signs_db = db.session.query(Sign).filter_by(team_id=team_id).all()
    return jsonify([model_to_dict(s) for s in signs_db])

@api_bp.route('/overview_data')
@login_required
def get_overview_data():
    team_id = session.get('team_id')
    if not team_id:
        return jsonify({"error": "Team not found"}), 404

    team = db.session.get(Team, team_id)

    next_game = db.session.query(Game).filter(
        Game.team_id == team_id,
        Game.date >= datetime.now()
    ).order_by(Game.date.asc()).first()

    roster_db = db.session.query(Player).filter_by(team_id=team_id).all()
    pitching_outings_db = db.session.query(PitchingOuting).options(joinedload(PitchingOuting.player)).filter_by(team_id=team_id).all()
    from models import PlayerPitchTarget
    all_targets = db.session.query(PlayerPitchTarget).filter_by(team_id=team_id).all()
    rules = get_pitching_rules_for_team(team)
    pitch_count_summary = calculate_pitch_count_summary(roster_db, pitching_outings_db, rules, all_targets=all_targets, team_timezone=team.timezone)
    pitchers_on_rest = {name: data for name, data in pitch_count_summary.items() if data['status'] == 'Resting'}

    recent_notes = db.session.query(CollaborationNote).filter_by(team_id=team_id).order_by(CollaborationNote.timestamp.desc()).limit(5).all()

    return jsonify({
        'next_game': model_to_dict(next_game) if next_game else None,
        'pitchers_on_rest': pitchers_on_rest,
        'recent_notes': [model_to_dict(n) for n in recent_notes]
    })


def get_live_game_state(game_id, team_id):
    """Legacy game-data helper retained for /api/game_data and old non-live consumers."""
    team = db.session.get(Team, team_id)
    game = db.session.query(Game).filter_by(id=game_id, team_id=team_id).first()
    if not game or not team:
        return None

    roster_objects = db.session.query(Player).filter_by(team_id=team_id).order_by(Player.name).all()
    lineup_obj = db.session.query(Lineup).filter_by(associated_game_id=game.id, team_id=team_id).first()
    rotation_obj = db.session.query(Rotation).filter_by(associated_game_id=game.id, team_id=team_id).first()

    all_pitching_outings = db.session.query(PitchingOuting).options(joinedload(PitchingOuting.player)).filter_by(team_id=team_id).all()
    game_pitching_log = [o for o in all_pitching_outings if o.opponent == game.opponent and o.date.date() == game.date.date()]

    absences = db.session.query(PlayerGameAbsence).filter_by(game_id=game.id, team_id=team_id).all()
    absent_player_ids = [absence.player_id for absence in absences]

    from models import PlayerPitchTarget, GameRotationEvent, GamePitchingPlan, PlayerPitchingProfile
    all_targets = db.session.query(PlayerPitchTarget).filter_by(team_id=team_id).all()
    rotation_events = db.session.query(GameRotationEvent).filter_by(game_id=game.id, team_id=team_id).order_by(GameRotationEvent.id).all()
    pitching_plans = db.session.query(GamePitchingPlan).filter_by(game_id=game.id, team_id=team_id).all()
    pitching_profiles = db.session.query(PlayerPitchingProfile).filter_by(team_id=team_id).all()

    rules = get_pitching_rules_for_team(team)
    pitch_count_summary = calculate_pitch_count_summary(roster_objects, all_pitching_outings, rules, target_date=game.date, all_targets=all_targets, team_timezone=team.timezone, current_game_id=game.id)

    lineup_templates = db.session.query(Lineup).filter_by(team_id=team_id, associated_game_id=None).all()
    rotation_templates = db.session.query(Rotation).filter_by(team_id=team_id, associated_game_id=None).all()

    import json
    actual_rotation = {}
    if rotation_obj and rotation_obj.innings:
        actual_rotation = json.loads(json.dumps(rotation_obj.innings))

    for event in rotation_events:
        if not event.reverted:
            actual_rotation[event.inning] = event.after_alignment

    return {
        'game': model_to_dict(game),
        'roster': [model_to_dict(p) for p in roster_objects],
        'lineup': model_to_dict(lineup_obj) if lineup_obj else None,
        'rotation': model_to_dict(rotation_obj) if rotation_obj else None,
        'actual_rotation': actual_rotation,
        'game_pitching_log': [pitching_outing_to_dict(o) for o in game_pitching_log],
        'absent_player_ids': absent_player_ids,
        'pitch_count_summary': pitch_count_summary,
        'lineup_templates': [model_to_dict(lt) for lt in lineup_templates],
        'rotation_templates': [model_to_dict(rt) for rt in rotation_templates],
        'outfielder_count': team.outfielder_count,
        'rotation_events': [model_to_dict(e) for e in rotation_events],
        'pitching_plans': [model_to_dict(pp) for pp in pitching_plans],
        'pitching_profiles': [model_to_dict(pp) for pp in pitching_profiles]
    }

@api_bp.route('/game_data/<int:game_id>')
@login_required
def get_game_data(game_id):
    team_id = session.get('team_id')
    if not team_id:
        return jsonify({"error": "Team not found"}), 404

    state = get_live_game_state(game_id, team_id)
    if not state:
        return jsonify({"error": "Game or Team not found"}), 404

    return jsonify(state)

@api_bp.route('/stats')
@login_required
def get_stats():
    team_id = session.get('team_id')
    if not team_id:
        return jsonify({"error": "Team not found"}), 404

    from actual_stats import calculate_actual_position_game_stats
    from models import GameRotationEvent

    roster_db = db.session.query(Player).filter_by(team_id=team_id).all()
    pitching_outings_db = db.session.query(PitchingOuting).options(joinedload(PitchingOuting.player)).filter_by(team_id=team_id).all()
    rotations_db = db.session.query(Rotation).filter_by(team_id=team_id).all()
    rotation_events_db = db.session.query(GameRotationEvent).filter_by(team_id=team_id).all()

    designated_pitchers = {p.id: p for p in roster_db if p.pitcher_role != 'Not a Pitcher'}
    players_with_outings = {o.player_id: o.player for o in pitching_outings_db if o.player is not None}
    combined_pitchers_dict = {**designated_pitchers, **players_with_outings}
    pitchers = list(combined_pitchers_dict.values())
    cumulative_pitching_data = {p.name: calculate_cumulative_pitching_stats(p.id, pitching_outings_db) for p in pitchers}
    cumulative_position_data = calculate_actual_position_game_stats(roster_db, rotations_db, rotation_events_db)

    game_absences = db.session.query(PlayerGameAbsence.player_id, func.count(PlayerGameAbsence.id)).filter_by(team_id=team_id).group_by(PlayerGameAbsence.player_id).all()
    practice_absences = db.session.query(PlayerPracticeAbsence.player_id, func.count(PlayerPracticeAbsence.id)).filter_by(team_id=team_id).group_by(PlayerPracticeAbsence.player_id).all()

    attendance_stats = {p.id: {'name': p.name, 'games_missed': 0, 'practices_missed': 0} for p in roster_db}
    for player_id, count in game_absences:
        if player_id in attendance_stats:
            attendance_stats[player_id]['games_missed'] = count
    for player_id, count in practice_absences:
        if player_id in attendance_stats:
            attendance_stats[player_id]['practices_missed'] = count

    return jsonify({
        'cumulative_pitching_data': cumulative_pitching_data,
        'cumulative_position_data': cumulative_position_data,
        'attendance_stats': attendance_stats
    })
