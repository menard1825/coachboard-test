from flask import jsonify, session

from db import db
from models import Game
from utils import model_to_dict
from . import api_bp
from .decorators import login_required

@api_bp.route('/games')
@login_required
def get_games():
    team_id = session.get('team_id')
    if not team_id:
        return jsonify({"error": "Team not found"}), 404

    games_db = db.session.query(Game).filter_by(team_id=team_id).all()
    return jsonify([model_to_dict(g) for g in games_db])
