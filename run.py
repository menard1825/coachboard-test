# run.py
import os
from dotenv import load_dotenv

# Load environment variables first
load_dotenv()

from app import create_app
from extensions import socketio

# Create the app instance using the factory
app = create_app()

if __name__ == '__main__':
    # IMPORTANT: Monkey patch only when running the server directly
    import eventlet
    eventlet.monkey_patch()

    print("Starting server with SocketIO...")
    debug_mode = os.environ.get('FLASK_DEBUG') == '1'
    # Use the Flask-SocketIO development server
    socketio.run(app, host='0.0.0.0', port=5005, debug=debug_mode)
