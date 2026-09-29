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
# Prefer the familiar port, but choose a free one if another process owns it.
with socket.socket() as probe:
    try:
        probe.bind(('0.0.0.0', 5006))
    except OSError:
        probe.bind(('0.0.0.0', 0))
    port = probe.getsockname()[1]
from app import create_app
app = create_app({'SECRET_KEY': secrets.token_hex(32),
                  'SESSION_COOKIE_NAME': 'coachboard_rollover_preview',
                  'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + str(ROOT / 'app.db'),
                  'SOCKETIO_ASYNC_MODE': 'threading'})
print(f'OPEN PREVIEW: http://192.168.86.72:{port} (on your home network). Use your existing coach login.', flush=True)
print('This is a disposable copy. Preview changes will NOT be applied to production. Ctrl+C stops the preview.', flush=True)
app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
