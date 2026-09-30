import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit
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


# "Has the 4th inning started?" (game_availability.py) is asked at the first
# On the Field change of an inning without a start marker. Browser tests of
# field behavior are not about that question, so every page answers "Not
# yet" for them: a change that doesn't say otherwise goes out with
# inning_started: false, which records nothing extra -- from the page (an init
# script wrapping fetch) and from Python (Playwright's request context). A
# test of the question itself sets window.__cbTestAskInningStart
# (ask_inning_start_question below) and gets the real sheet; a Python request
# that sends its own inning_started is left alone.
INNING_START_DEFAULT_SCRIPT = r"""
(() => {
  const onTheField = /\/api\/live-game\/\d+\/(defensive-change|defense-edit|set-defense|complete-pitcher-change|change-pitcher)$/;
  const fetchWithoutDefault = window.fetch.bind(window);
  window.fetch = (input, init) => {
    try {
      const url = typeof input === 'string' ? input : input?.url;
      const path = new URL(url, window.location.href).pathname;
      const method = String(init?.method || 'GET').toUpperCase();
      if (!window.__cbTestAskInningStart && method === 'POST' && onTheField.test(path)
          && typeof input === 'string' && typeof init?.body === 'string') {
        const body = JSON.parse(init.body);
        if (body && typeof body === 'object' && body.inning_started === undefined) {
          init = {...init, body: JSON.stringify({...body, inning_started: false})};
        }
      }
    } catch (_) {}
    return fetchWithoutDefault(input, init);
  };
})();
"""

ASK_INNING_START_SCRIPT = 'window.__cbTestAskInningStart = true;'
ON_THE_FIELD_PATH = re.compile(
    r'/api/live-game/\d+/(defensive-change|defense-edit|set-defense|complete-pitcher-change|change-pitcher)$'
)


def ask_inning_start_question(context_or_page):
    """Opt this context/page out of the Not yet default: the real sheet asks."""
    context_or_page.add_init_script(ASK_INNING_START_SCRIPT)


@pytest.fixture(scope='session', autouse=True)
def _answer_inning_start_not_yet_by_default():
    try:
        from playwright.sync_api._generated import APIRequestContext, Browser
    except ImportError:  # the unit suite runs without Playwright
        yield
        return

    original_new_context = Browser.new_context
    original_new_page = Browser.new_page
    original_post = APIRequestContext.post

    def post(self, url, *args, **kwargs):
        data = kwargs.get('data')
        if (isinstance(data, dict) and 'inning_started' not in data
                and ON_THE_FIELD_PATH.search(urlsplit(url).path)):
            kwargs['data'] = {**data, 'inning_started': False}
        return original_post(self, url, *args, **kwargs)

    def new_context(self, *args, **kwargs):
        context = original_new_context(self, *args, **kwargs)
        context.add_init_script(INNING_START_DEFAULT_SCRIPT)
        return context

    def new_page(self, *args, **kwargs):
        page = original_new_page(self, *args, **kwargs)
        page.add_init_script(INNING_START_DEFAULT_SCRIPT)
        return page

    Browser.new_context = new_context
    Browser.new_page = new_page
    APIRequestContext.post = post
    try:
        yield
    finally:
        Browser.new_context = original_new_context
        Browser.new_page = original_new_page
        APIRequestContext.post = original_post
