from flask import jsonify, session
from sqlalchemy.orm import joinedload
from sqlalchemy import func

from db import db
from models import Player, PitchingOuting, Rotation, PlayerGameAbsence, PlayerPracticeAbsence, Game
from utils import calculate_cumulative_pitching_stats, calculate_cumulative_position_stats
from . import api_bp
from .decorators import login_required

@api_bp.route('/stats')
@login_required
def get_stats():
    team_id = session.get('team_id')
    if not team_id:
        return jsonify({"error": "Team not found"}), 404

    roster_db = db.session.query(Player).filter_by(team_id=team_id).all()
    pitching_outings_db = db.session.query(PitchingOuting).options(joinedload(PitchingOuting.player)).filter_by(team_id=team_id).all()

    # --- MODIFICATION START ---
    # Query for rotations for position stats, but only those associated with a game.
    rotations_db = db.session.query(Rotation).join(Game, Rotation.associated_game_id == Game.id).filter(Rotation.team_id == team_id).all()
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
