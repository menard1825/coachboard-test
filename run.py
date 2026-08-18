import os

from dotenv import load_dotenv

# Load a server-local .env before importing extensions/app because Socket.IO and
# security configuration read environment variables during module import.
load_dotenv()

import eventlet

eventlet.monkey_patch()

from app import create_app
from extensions import socketio

app = create_app()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5002))
    debug = str(os.environ.get('COACHBOARD_DEBUG') or '').strip().lower() in {'1', 'true', 'yes', 'on'}
    print(f'Starting CoachBoard on port {port} (debug={debug})...')
    socketio.run(app, host='0.0.0.0', port=port, debug=debug)
