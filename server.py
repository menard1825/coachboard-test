# server.py
import eventlet
eventlet.monkey_patch()

import os
from run import app
from extensions import socketio

if __name__ == '__main__':
    print("Starting server with SocketIO...")
    debug_mode = os.environ.get('FLASK_DEBUG') == '1'
    socketio.run(app, host='0.0.0.0', port=5005, debug=debug_mode)
