from flask import jsonify, session
from sqlalchemy.orm import joinedload

from db import db
from models import Team, Player, PitchingOuting
from utils import pitching_outing_to_dict, get_pitching_rules_for_team, calculate_pitch_count_summary
from . import api_bp
from .decorators import login_required

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
