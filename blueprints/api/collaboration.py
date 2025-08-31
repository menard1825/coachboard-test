from flask import jsonify, session

from db import db
from models import CollaborationNote
from utils import model_to_dict
from . import api_bp
from .decorators import login_required

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
