import re

from flask import Blueprint, jsonify, request, session

from db import db
from models import Game, Rotation


# Compatibility blueprint: the existing gameday route still owns /game/<id>,
# while this layer protects planned rotations and loads the server-authoritative
# live-game enhancements without requiring the legacy template to own them.
live_game_ui_bp = Blueprint('live_game_ui', __name__)


@live_game_ui_bp.before_app_request
def protect_planned_rotation_while_live():
    """Never let legacy planner autosave overwrite a live game's plan.

    Live defensive changes belong in GameRotationEvent. Rotation.innings remains
    the pregame plan and becomes editable again after the game is no longer live.
    """
    if request.method != 'POST' or request.endpoint != 'gameday.save_rotation':
        return None

    team_id = session.get('team_id')
    if not team_id:
        return None

    payload = request.get_json(silent=True) or {}
    game_id = payload.get('associated_game_id')

    if not game_id and payload.get('id'):
        try:
            rotation_id = int(payload.get('id'))
        except (TypeError, ValueError):
            rotation_id = None
        if rotation_id:
            rotation = db.session.query(Rotation).filter_by(id=rotation_id, team_id=team_id).first()
            if rotation:
                game_id = rotation.associated_game_id

    try:
        game_id = int(game_id) if game_id not in (None, '') else None
    except (TypeError, ValueError):
        game_id = None

    if not game_id:
        return None

    game = db.session.query(Game).filter_by(id=game_id, team_id=team_id).first()
    if game and game.is_live:
        return jsonify({
            'status': 'error',
            'message': 'The planned defensive rotation is locked while this game is live. Use Live Game changes instead.'
        }), 409

    return None


@live_game_ui_bp.after_app_request
def inject_live_game_assets(response):
    """Load the final live-game helpers on Game Management pages.

    This also prevents the legacy live overlay from flashing before the polished
    dugout UI is ready. A fallback reveals the legacy UI after a short delay if
    the enhancement scripts fail for any reason.
    """
    if response.mimetype != 'text/html' or not re.fullmatch(r'/game/\d+/?', request.path):
        return response

    html = response.get_data(as_text=True)

    if 'coach-live-first-paint' not in html:
        first_paint = '''
<style id="coach-live-first-paint">
  #live-game-overlay:not(.coach-live-polished):not(.coach-live-boot-fallback) {
    visibility: hidden !important;
  }
  #pregame-checklist-container > .d-flex:first-child .bi {
    display: none !important;
  }
</style>
'''
        if '</head>' in html:
            html = html.replace('</head>', first_paint + '</head>', 1)
        else:
            html = first_paint + html

    if 'live_game_board_prep_v2.js' not in html:
        assets = '''
<script>
  window.setTimeout(function () {
    var overlay = document.getElementById('live-game-overlay');
    if (overlay && !overlay.classList.contains('coach-live-polished')) {
      overlay.classList.add('coach-live-boot-fallback');
    }
  }, 2500);
</script>
<script src="/static/js/live_game_pitcher_change_complete.js"></script>
<script src="/static/js/live_game_board_prep_v2.js"></script>
<script src="/static/js/live_game_postgame_cleanup.js"></script>
'''
        if '</body>' in html:
            html = html.replace('</body>', assets + '</body>', 1)
        else:
            html += assets

    response.set_data(html)
    return response
