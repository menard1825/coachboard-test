from flask import jsonify, session

from db import db
from models import Player, PlayerDevelopmentFocus
from utils import model_to_dict
from . import api_bp
from .decorators import login_required

@api_bp.route('/player_development')
@login_required
def get_player_development():
    team_id = session.get('team_id')
    if not team_id:
        return jsonify({"error": "Team not found"}), 404

    roster_db = db.session.query(Player).filter_by(team_id=team_id).all()
    player_dev_focuses = db.session.query(PlayerDevelopmentFocus).filter_by(team_id=team_id).all()

    player_dev_by_name = {p.name: [] for p in roster_db}
    player_id_to_name = {p.id: p.name for p in roster_db}

    for focus in player_dev_focuses:
        player_name = player_id_to_name.get(focus.player_id)
        if player_name:
            focus_dict = model_to_dict(focus)
            focus_dict.update({
                'type': 'Development',
                'subtype': focus.skill_type.capitalize(),
                'text': focus.focus,
                'date': focus.created_date.strftime('%Y-%m-%d')
            })
            player_dev_by_name[player_name].append(focus_dict)

    return jsonify(player_dev_by_name)
