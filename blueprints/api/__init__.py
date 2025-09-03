from flask import Blueprint

# This is the main blueprint for the API.
# Other API modules will be registered with this blueprint.
api_bp = Blueprint('api', __name__, url_prefix='/api')

# Import the other API modules to register their routes
from . import roster, session, lineups, pitching, scouting, rotations, games, collaboration, practice, player_dev, signs, overview, stats, weather, places
