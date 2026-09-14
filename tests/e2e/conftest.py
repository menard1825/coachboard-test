import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _available_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


@pytest.fixture(scope='session')
def coachboard_url(tmp_path_factory):
    """Run CoachBoard against a disposable SQLite database for browser tests."""
    if os.environ.get('COACHBOARD_E2E') != '1':
        pytest.skip('Set COACHBOARD_E2E=1 to run the Playwright suite.')

    runtime_dir = tmp_path_factory.mktemp('coachboard-e2e')
    database_path = runtime_dir / 'coachboard-e2e.db'
    port = _available_port()
    base_url = f'http://127.0.0.1:{port}'
    env = os.environ.copy()
    env.update({
        'ASSET_VERSION': 'e2e',
        'COACHBOARD_ENV': 'test',
        'DATABASE_URL': f'sqlite:///{database_path}',
        'E2E_PORT': str(port),
        'PYTHONUNBUFFERED': '1',
        'SECRET_KEY': 'coachboard-e2e-only-secret',
        'SESSION_COOKIE_SECURE': '0',
    })

    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).with_name('serve_test_app.py'))],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    deadline = time.monotonic() + 30
    startup_error = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = process.communicate()[0]
            raise RuntimeError(f'CoachBoard E2E server exited during startup:\n{output}')
        try:
            with urlopen(f'{base_url}/login', timeout=1) as response:
                if response.status == 200:
                    startup_error = None
                    break
        except (OSError, URLError) as error:
            startup_error = error
            time.sleep(0.2)
    else:
        process.terminate()
        output = process.communicate(timeout=10)[0]
        raise RuntimeError(
            f'CoachBoard E2E server did not become ready: {startup_error}\n{output}'
        )

    yield base_url

    process.terminate()
    try:
        process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate(timeout=5)
