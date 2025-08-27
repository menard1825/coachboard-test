from flask import Blueprint, jsonify, session
from db import db
from models import User, Team, Player, Lineup, PitchingOuting, ScoutedPlayer, Rotation, Game, CollaborationNote, PracticePlan, PlayerDevelopmentFocus, Sign, PlayerGameAbsence, PlayerPracticeAbsence
from blueprints.auth import get_player_order_as_list
from utils import model_to_dict, pitching_outing_to_dict, get_pitching_rules_for_team, calculate_pitch_count_summary, calculate_cumulative_pitching_stats, calculate_cumulative_position_stats
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
    if not user:
        return jsonify({"error": "User not found"}), 404

    return jsonify({
        'session': {'username': session.get('username'), 'role': session.get('role')},
        # Use the helper function to ensure it's always a list
        'player_order': get_player_order_as_list(user.player_order),
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

    rules = get_pitching_rules_for_team(team)
    pitch_count_summary = calculate_pitch_count_summary(roster_db, pitching_outings_db, rules)

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

    # 1. Next upcoming game
    next_game = db.session.query(Game).filter(
        Game.team_id == team_id,
        Game.date >= datetime.utcnow()
    ).order_by(Game.date.asc()).first()

    # 2. Pitchers on mandatory rest
    roster_db = db.session.query(Player).filter_by(team_id=team_id).all()
    pitching_outings_db = db.session.query(PitchingOuting).options(joinedload(PitchingOuting.player)).filter_by(team_id=team_id).all()
    rules = get_pitching_rules_for_team(team)
    pitch_count_summary = calculate_pitch_count_summary(roster_db, pitching_outings_db, rules)
    pitchers_on_rest = {name: data for name, data in pitch_count_summary.items() if data['status'] == 'Resting'}

    # 3. 3-5 most recent collaboration notes
    recent_notes = db.session.query(CollaborationNote).filter_by(team_id=team_id).order_by(CollaborationNote.timestamp.desc()).limit(5).all()

    return jsonify({
        'next_game': model_to_dict(next_game) if next_game else None,
        'pitchers_on_rest': pitchers_on_rest,
        'recent_notes': [model_to_dict(n) for n in recent_notes]
    })


@api_bp.route('/stats')
@login_required
def get_stats():
    team_id = session.get('team_id')
    if not team_id:
        return jsonify({"error": "Team not found"}), 404

    roster_db = db.session.query(Player).filter_by(team_id=team_id).all()
    pitching_outings_db = db.session.query(PitchingOuting).options(joinedload(PitchingOuting.player)).filter_by(team_id=team_id).all()

    # --- MODIFICATION START ---
    # Query for rotations for position stats
    rotations_db = db.session.query(Rotation).filter_by(team_id=team_id).all()
    # --- MODIFICATION END ---

    # Get players designated as pitchers
    designated_pitchers = {p.id: p for p in roster_db if p.pitcher_role != 'Not a Pitcher'}

    # Get players who have any pitching outings logged
    players_with_outings = {o.player_id: o.player for o in pitching_outings_db if o.player is not None}

    # Combine the two lists (duplicates are handled by the dictionary)
    combined_pitchers_dict = {**designated_pitchers, **players_with_outings}

    # This is the final list of all players who should be in the summary
    pitchers = list(combined_pitchers_dict.values())
    cumulative_pitching_data = {p.name: calculate_cumulative_pitching_stats(p.id, pitching_outings_db) for p in pitchers}

    # --- MODIFICATION START ---
    # Pass rotations_db to the function
    cumulative_position_data = calculate_cumulative_position_stats(roster_db, rotations_db)
    # --- MODIFICATION END ---

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
