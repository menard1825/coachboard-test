# extensions.py
from flask_socketio import SocketIO
from flask_migrate import Migrate
# MODIFIED: Changed from relative to absolute import
from db import db

# Create the instances here, but don't attach them to an app yet.
socketio = SocketIO()
migrate = Migrate()