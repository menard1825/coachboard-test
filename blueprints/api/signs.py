from flask import jsonify, session

from db import db
from models import Sign
from utils import model_to_dict
from . import api_bp
from .decorators import login_required

@api_bp.route('/signs')
@login_required
def get_signs():
    team_id = session.get('team_id')
    if not team_id:
        return jsonify({"error": "Team not found"}), 404

    signs_db = db.session.query(Sign).filter_by(team_id=team_id).all()
    return jsonify([model_to_dict(s) for s in signs_db])
