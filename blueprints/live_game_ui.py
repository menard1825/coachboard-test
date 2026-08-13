from flask import Blueprint

# Compatibility blueprint: the live game UI is rendered by the existing
# gameday game-management route, while static/js/live_game_v2.js provides
# the server-authoritative live lifecycle controller.
live_game_ui_bp = Blueprint('live_game_ui', __name__)
