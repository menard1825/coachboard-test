import eventlet
print("Starting server...")
eventlet.monkey_patch()

from app import create_app
from extensions import socketio

app = create_app()

import os

if __name__ == '__main__':
    # Use socketio.run() to start the development server
    port = int(os.environ.get('PORT', 5002))
    socketio.run(app, host='0.0.0.0', port=port, debug=True)
