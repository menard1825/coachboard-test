from flask import jsonify, session

from db import db
from models import Lineup
from utils import model_to_dict
from . import api_bp
from .decorators import login_required

@api_bp.route('/lineups')
@login_required
def get_lineups():
    team_id = session.get('team_id')
    if not team_id:
        return jsonify({"error": "Team not found"}), 404

    lineups_db = db.session.query(Lineup).filter_by(team_id=team_id).all()
    return jsonify([model_to_dict(l) for l in lineups_db])
