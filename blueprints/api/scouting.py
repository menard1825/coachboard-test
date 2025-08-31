from flask import jsonify, session

from db import db
from models import ScoutedPlayer
from utils import model_to_dict
from . import api_bp
from .decorators import login_required

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
