from flask import jsonify, session
from sqlalchemy.orm import joinedload

from db import db
from models import User
from blueprints.auth import get_player_order_as_list
from . import api_bp
from .decorators import login_required

@api_bp.route('/session_data')
@login_required
def get_session_data():
    user = db.session.query(User).options(joinedload(User.team)).filter_by(username=session['username']).first()
    if not user or not user.team:
        return jsonify({"error": "User or team not found"}), 404

    return jsonify({
        'session': {
            'username': session.get('username'),
            'role': session.get('role'),
            'outfielder_count': user.team.outfielder_count if user.team else 3
        },
        'player_order': get_player_order_as_list(user.player_order),
    })
