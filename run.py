import eventlet
eventlet.monkey_patch()

from app import create_app
from extensions import socketio

app = create_app()

if __name__ == '__main__':
    # Use socketio.run() to start the development server
    socketio.run(app, host='0.0.0.0', port=5002, debug=True)
