from flask import jsonify, session

from db import db
from models import Rotation
from utils import model_to_dict
from . import api_bp
from .decorators import login_required

@api_bp.route('/rotations')
@login_required
def get_rotations():
    team_id = session.get('team_id')
    if not team_id:
        return jsonify({"error": "Team not found"}), 404

    rotations_db = db.session.query(Rotation).filter_by(team_id=team_id).all()
    return jsonify([model_to_dict(r) for r in rotations_db])
