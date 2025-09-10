import eventlet
import os
from dotenv import load_dotenv

print("Starting server...")
eventlet.monkey_patch()

load_dotenv()

from app import create_app
from extensions import socketio

app = create_app()

if __name__ == '__main__':
    # Debug mode is now controlled by the FLASK_DEBUG environment variable
    debug_mode = os.environ.get('FLASK_DEBUG') == '1'
    socketio.run(app, host='0.0.0.0', port=5005, debug=debug_mode)
