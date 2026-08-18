from flask import Blueprint, redirect, request, session, url_for

from db import db
from models import Game, GameRotationEvent


postgame_navigation_bp = Blueprint('postgame_navigation', __name__)


@postgame_navigation_bp.before_app_request
def route_completed_game_to_report():
    """Keep completed games in the actual-game workflow, not the pregame planner.

    `/game/<id>` is the historical Game Management route and still contains
    pregame lineup/rotation/pitching planning tools. Once a durable End Game
    event exists, opening that URL normally should show the Actual Game Report.

    Explicit postgame tools may opt into the old shell:
    - ?pitching=1 opens focused GameChanger stat entry.
    - ?edit=1 intentionally opens the setup/review screen.
    """
    if request.method != 'GET' or request.endpoint != 'gameday.game_management':
        return None

    if request.args.get('pitching') == '1' or request.args.get('edit') == '1':
        return None

    team_id = session.get('team_id')
    if not team_id:
        return None

    try:
        game_id = int((request.view_args or {}).get('game_id'))
    except (TypeError, ValueError):
        return None

    game = db.session.query(Game).filter_by(id=game_id, team_id=team_id).first()
    if not game or game.is_live:
        return None

    has_end_game = db.session.query(GameRotationEvent.id).filter_by(
        game_id=game.id,
        team_id=team_id,
        event_type='End Game',
        reverted=False,
    ).first() is not None

    if not has_end_game:
        return None

    return redirect(url_for('game_day.game_report', game_id=game.id))
