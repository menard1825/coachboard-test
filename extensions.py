# extensions.py
from flask_socketio import SocketIO

# Create the SocketIO instance here, but don't attach it to an app yet.
# Blueprints will import this object directly.
socketio = SocketIO()