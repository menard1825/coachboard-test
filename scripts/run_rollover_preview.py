"""Run only the prepared preview database; uses its own login cookie and secret."""
import os
from pathlib import Path
import secrets
import socket
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if ROOT.name != 'coachboard-prod-rollover-preview' or not (ROOT / 'app.db').is_file():
    raise SystemExit('Run from the prepared coachboard-prod-rollover-preview checkout only.')
# Refuse a busy preview port rather than disrupting an existing process.
with socket.socket() as probe:
    probe.bind(('0.0.0.0', 5006))
from app import create_app
app = create_app({'SECRET_KEY': secrets.token_hex(32),
                  'SESSION_COOKIE_NAME': 'coachboard_rollover_preview',
                  'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + str(ROOT / 'app.db'),
                  'SOCKETIO_ASYNC_MODE': 'threading'})
print('Preview: http://192.168.86.72:5006 (on your home network). Use your existing coach login.', flush=True)
print('This is a disposable copy. Preview changes will NOT be applied to production. Ctrl+C stops the preview.', flush=True)
app.run(host='0.0.0.0', port=5006, debug=False, threaded=True)
