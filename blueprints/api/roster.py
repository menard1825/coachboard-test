from flask import jsonify, session

from db import db
from models import Player
from utils import model_to_dict
from . import api_bp
from .decorators import login_required

@api_bp.route('/roster')
@login_required
def get_roster():
    team_id = session.get('team_id')
    if not team_id:
        return jsonify({"error": "Team not found"}), 404

    roster_db = db.session.query(Player).filter_by(team_id=team_id).all()
    return jsonify([model_to_dict(p) for p in roster_db])
