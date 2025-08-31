from flask import jsonify, session
from sqlalchemy.orm import joinedload

from db import db
from models import PracticePlan
from utils import model_to_dict
from . import api_bp
from .decorators import login_required

@api_bp.route('/practice_plans')
@login_required
def get_practice_plans():
    team_id = session.get('team_id')
    if not team_id:
        return jsonify({"error": "Team not found"}), 404

    practice_plans_q = db.session.query(PracticePlan).filter_by(team_id=team_id).options(joinedload(PracticePlan.tasks), joinedload(PracticePlan.absences)).all()

    practice_plans_list = []
    for p in practice_plans_q:
        plan_dict = model_to_dict(p)
        plan_dict['tasks'] = [model_to_dict(t) for t in p.tasks]
        plan_dict['absent_player_ids'] = [a.player_id for a in p.absences]
        practice_plans_list.append(plan_dict)

    return jsonify(practice_plans_list)
