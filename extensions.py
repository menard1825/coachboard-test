import os

from flask_socketio import SocketIO
from flask_migrate import Migrate

from db import db


def _socketio_origins():
    value = str(os.environ.get('SOCKETIO_CORS_ORIGINS') or '').strip()
    if not value:
        # None means same-origin protection instead of accepting every website.
        return None
    origins = [item.strip() for item in value.split(',') if item.strip()]
    return origins or None


# Create the instances here, but don't attach them to an app yet.
socketio = SocketIO(cors_allowed_origins=_socketio_origins())
migrate = Migrate()
