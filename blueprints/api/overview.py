from flask import jsonify, session
from sqlalchemy.orm import joinedload
from datetime import datetime

from db import db
from models import Team, Player, PitchingOuting, Game, CollaborationNote
from utils import model_to_dict, get_pitching_rules_for_team, calculate_pitch_count_summary
from . import api_bp
from .decorators import login_required

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
