# run.py

# IMPORTANT: eventlet.monkey_patch() must be the very first thing to run
import eventlet
eventlet.monkey_patch()

import os
from dotenv import load_dotenv

# Now, we can load environment variables and import the app
load_dotenv()

from app import create_app
from extensions import socketio

print("Starting server...")

app = create_app()

if __name__ == '__main__':
    debug_mode = os.environ.get('FLASK_DEBUG') == '1'
    # Use the Flask-SocketIO development server
    socketio.run(app, host='0.0.0.0', port=5005, debug=debug_mode)
