"""The live game overlay is painted hidden and revealed by script.

`inject_live_game_assets` ships a stylesheet that hides #live-game-overlay
until live_game_coach_ui.js marks it polished. That trade only works if the
reveal ships too -- an overlay hidden with nothing left to reveal it is a
coach staring at an empty screen mid-inning.

The reveal also has to respect `d-none`. An overlay carrying it is deliberately
off screen and the gate is not what is hiding it, so spending the gate early
would only let the raw board flash when the live controller shows the overlay
later. The lifecycle tests below run the injected script itself under a stubbed
DOM rather than asserting on its source text, because "does not fall back while
d-none" is a behavioural claim that string matching cannot make.
"""
import json
import re
import shutil
import subprocess
from datetime import datetime

import pytest
from flask import Response
from werkzeug.security import generate_password_hash


OVERLAY_HIDDEN_MARKER = 'coach-live-first-paint'
BOOT_REVEAL_MARKER = 'coach-live-boot-reveal'

NODE = shutil.which('node')
requires_node = pytest.mark.skipif(NODE is None, reason='node is required to run the injected script')


def _build_app(monkeypatch):
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')

    from app import create_app
    from db import db
    from models import Game, Team, TeamMembership, User

    app = create_app()
    app.config.update(TESTING=True)

    with app.app_context():
        db.create_all()
        team = Team(
            id=1,
            team_name='Boot Reveal Team',
            registration_code='boot-reveal-code',
            age_group='9U',
            pitching_rule_set='MLB Pitch Smart',
            outfielder_count=3,
            timezone='America/Indiana/Indianapolis',
        )
        user = User(
            id=1,
            username='coach',
            full_name='Test Coach',
            password_hash=generate_password_hash('password123'),
        )
        db.session.add_all([team, user])
        db.session.flush()
        db.session.add(TeamMembership(
            user_id=user.id,
            team_id=team.id,
            role='Head Coach',
            player_order=[],
        ))
        db.session.add(Game(
            id=70,
            date=datetime(2026, 8, 30, 17, 0, 0),
            opponent='Boot Reveal Test',
            team_id=team.id,
            is_live=True,
            live_current_inning='2',
        ))
        db.session.commit()

    return app


def _inject(app, html):
    from blueprints.live_game_ui import inject_live_game_assets

    with app.test_request_context('/game/70'):
        response = inject_live_game_assets(Response(html, mimetype='text/html'))
    return response.get_data(as_text=True)


def _page(extra_body=''):
    return (
        '<html><head></head><body>'
        '<div id="live-game-overlay" class=""></div>'
        f'{extra_body}'
        '</body></html>'
    )


def _reveal_script(body):
    match = re.search(
        rf'<script id="{BOOT_REVEAL_MARKER}">(.*?)</script>',
        body,
        re.DOTALL,
    )
    assert match, 'the boot reveal script was not injected'
    return match.group(1)


# The stub models only what the reveal script touches: a single overlay whose
# class list notifies observers, a load event, DOMContentLoaded, and a timer
# queue the driver drains by deadline. MutationObserver callbacks fire
# synchronously here rather than on a microtask; the script only ever responds
# to one by scheduling a timer, so the distinction cannot change an outcome.
#
# Each scenario reports three things: whether the fallback class landed, how
# many grace timers were ever scheduled (to prove class churn cannot pile them
# up), and how many observers are still connected (to prove cleanup).
HARNESS = r'''
'use strict';
const fs = require('fs');
const SOURCE = fs.readFileSync(process.argv[2], 'utf8');

// Mirrors GRACE_MS in the injected script.
const GRACE_MS = 400;

function makeEnv(initialClasses) {
  const classes = new Set(initialClasses);
  let observers = [];
  let timers = [];
  const scheduled = [];
  const loadHandlers = [];
  const readyHandlers = [];

  function notify() {
    observers.slice().forEach((entry) => entry.cb());
  }

  const overlay = {
    classList: {
      contains: (name) => classes.has(name),
      add: (name) => {
        if (classes.has(name)) return;
        classes.add(name);
        notify();
      },
      remove: (name) => {
        if (!classes.has(name)) return;
        classes.delete(name);
        notify();
      },
    },
  };

  const documentStub = {
    readyState: 'loading',
    getElementById: (id) => (id === 'live-game-overlay' ? overlay : null),
    addEventListener: (type, fn) => {
      if (type === 'DOMContentLoaded') readyHandlers.push(fn);
    },
  };

  const windowStub = {
    addEventListener: (type, fn) => {
      if (type === 'load') loadHandlers.push(fn);
    },
    setTimeout: (fn, ms) => {
      scheduled.push(ms);
      timers.push({ fn, ms });
    },
    MutationObserver: function (cb) {
      this.observe = () => { observers.push({ cb }); };
      this.disconnect = () => { observers = observers.filter((e) => e.cb !== cb); };
    },
  };

  return {
    overlay,
    start: () => new Function('window', 'document', SOURCE)(windowStub, documentStub),
    domReady: () => {
      documentStub.readyState = 'interactive';
      readyHandlers.slice().forEach((fn) => fn());
    },
    load: () => loadHandlers.slice().forEach((fn) => fn()),
    flush: (deadline) => {
      for (let pass = 0; pass < 10; pass += 1) {
        const due = timers.filter((t) => t.ms <= deadline);
        if (!due.length) return;
        timers = timers.filter((t) => t.ms > deadline);
        due.forEach((t) => t.fn());
      }
    },
    fellBack: () => classes.has('coach-live-boot-fallback'),
    graceTimers: () => scheduled.filter((ms) => ms === GRACE_MS).length,
    observers: () => observers.length,
  };
}

function booted(initialClasses) {
  const env = makeEnv(initialClasses);
  env.start();
  env.domReady();
  return env;
}

function report(env, extra) {
  return Object.assign({
    fellBack: env.fellBack(),
    graceTimers: env.graceTimers(),
    observers: env.observers(),
  }, extra || {});
}

const scenarios = {
  visible_unpolished_at_load() {
    const env = booted([]);
    env.load();
    return report(env);
  },
  hidden_unpolished_at_load() {
    const env = booted(['d-none']);
    env.load();
    return report(env);
  },
  polished_at_load() {
    const env = booted(['coach-live-polished']);
    env.load();
    return report(env);
  },
  hidden_at_load_then_shown_never_polished() {
    const env = booted(['d-none']);
    env.load();
    env.overlay.classList.remove('d-none');
    env.flush(1000);
    return report(env);
  },
  hidden_at_load_then_shown_then_polished() {
    const env = booted(['d-none']);
    env.load();
    env.overlay.classList.remove('d-none');
    env.overlay.classList.add('coach-live-polished');
    env.flush(1000);
    return report(env);
  },
  visible_unpolished_load_never_fires() {
    const env = booted([]);
    env.flush(2500);
    return report(env);
  },
  hidden_unpolished_load_never_fires() {
    const env = booted(['d-none']);
    env.flush(2500);
    return report(env);
  },

  // Class churn on a visible, unpolished overlay must arm exactly one grace
  // timer, not one per mutation.
  many_visible_mutations_before_grace() {
    const env = booted(['d-none']);
    env.load();
    env.overlay.classList.remove('d-none');
    for (let i = 0; i < 12; i += 1) {
      env.overlay.classList.add('churn-' + i);
      env.overlay.classList.remove('churn-' + i);
    }
    const graceTimersBeforeGrace = env.graceTimers();
    env.flush(1000);
    return report(env, { graceTimersBeforeGrace });
  },

  // Deliberately never flushes: the polish mutation itself has to settle the
  // lifecycle and drop the observer, without waiting on another mutation.
  polished_settles_without_further_mutation() {
    const env = booted(['d-none']);
    env.load();
    env.overlay.classList.remove('d-none');
    env.overlay.classList.add('coach-live-polished');
    return report(env);
  },

  // Shown, then hidden again before the grace expires. The grace attempt is
  // spent on a d-none overlay, which must not settle or disarm anything.
  shown_then_hidden_before_grace_stays_armed() {
    const env = booted(['d-none']);
    env.load();
    env.overlay.classList.remove('d-none');
    env.overlay.classList.add('d-none');
    env.flush(1000);
    return report(env);
  },

  // ...and the same overlay shown a second time still falls back.
  shown_hidden_then_shown_again_falls_back() {
    const env = booted(['d-none']);
    env.load();
    env.overlay.classList.remove('d-none');
    env.overlay.classList.add('d-none');
    env.flush(1000);
    env.overlay.classList.remove('d-none');
    env.flush(2000);
    return report(env);
  },
};

const results = {};
Object.keys(scenarios).forEach((name) => { results[name] = scenarios[name](); });
process.stdout.write(JSON.stringify(results));
'''


@pytest.fixture(scope='module')
def lifecycle(tmp_path_factory, monkeypatch_module):
    """Run every lifecycle scenario against the real injected script once."""
    app = _build_app(monkeypatch_module)
    script = _reveal_script(_inject(app, _page()))

    workdir = tmp_path_factory.mktemp('boot-reveal')
    script_path = workdir / 'reveal.js'
    harness_path = workdir / 'harness.js'
    script_path.write_text(script, encoding='utf-8')
    harness_path.write_text(HARNESS, encoding='utf-8')

    completed = subprocess.run(
        [NODE, str(harness_path), str(script_path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


@pytest.fixture(scope='module')
def monkeypatch_module():
    from _pytest.monkeypatch import MonkeyPatch

    patcher = MonkeyPatch()
    yield patcher
    patcher.undo()


# --- lifecycle -------------------------------------------------------------

@requires_node
def test_visible_unpolished_overlay_falls_back_at_load(lifecycle):
    result = lifecycle['visible_unpolished_at_load']
    assert result['fellBack'] is True
    assert result['observers'] == 0


@requires_node
def test_hidden_overlay_does_not_fall_back_merely_because_load_fired(lifecycle):
    """d-none is not the gate hiding it, so the gate must not be spent here."""
    result = lifecycle['hidden_unpolished_at_load']
    assert result['fellBack'] is False
    assert result['observers'] == 1, 'the watcher must stay armed for the show'


@requires_node
def test_polished_overlay_never_falls_back(lifecycle):
    result = lifecycle['polished_at_load']
    assert result['fellBack'] is False
    assert result['observers'] == 0


@requires_node
def test_overlay_shown_after_load_still_gets_a_fallback(lifecycle):
    """The deliberate answer for a hidden overlay shown later by the live
    controller while the polish script is broken: watch for the transition and
    fall back after a grace window, rather than pre-applying the class."""
    result = lifecycle['hidden_at_load_then_shown_never_polished']
    assert result['fellBack'] is True
    assert result['observers'] == 0


@requires_node
def test_overlay_shown_then_polished_does_not_fall_back(lifecycle):
    result = lifecycle['hidden_at_load_then_shown_then_polished']
    assert result['fellBack'] is False
    assert result['observers'] == 0


@requires_node
def test_ceiling_still_reveals_when_load_never_fires(lifecycle):
    assert lifecycle['visible_unpolished_load_never_fires']['fellBack'] is True


@requires_node
def test_ceiling_respects_a_hidden_overlay_too(lifecycle):
    result = lifecycle['hidden_unpolished_load_never_fires']
    assert result['fellBack'] is False
    assert result['observers'] == 1


@requires_node
def test_class_churn_arms_only_one_grace_timer(lifecycle):
    """Twelve mutations on a visible, unpolished overlay used to queue twelve
    independent grace timers. Harmless individually, unbounded in aggregate."""
    result = lifecycle['many_visible_mutations_before_grace']
    assert result['graceTimersBeforeGrace'] == 1
    assert result['graceTimers'] == 1
    assert result['fellBack'] is True
    assert result['observers'] == 0


@requires_node
def test_polish_settles_the_lifecycle_without_another_mutation(lifecycle):
    """No timers are flushed in this scenario: the polish mutation itself has
    to settle and disconnect, rather than leaving the observer connected until
    some later class change happens to re-enter it."""
    result = lifecycle['polished_settles_without_further_mutation']
    assert result['observers'] == 0
    assert result['fellBack'] is False


@requires_node
def test_hidden_again_before_grace_does_not_disarm_the_fallback(lifecycle):
    result = lifecycle['shown_then_hidden_before_grace_stays_armed']
    assert result['fellBack'] is False
    assert result['observers'] == 1, 'a spent grace attempt must leave it armed'


@requires_node
def test_overlay_shown_a_second_time_can_still_fall_back(lifecycle):
    result = lifecycle['shown_hidden_then_shown_again_falls_back']
    assert result['fellBack'] is True
    assert result['observers'] == 0


# --- injection -------------------------------------------------------------

def test_hiding_the_overlay_always_ships_a_reveal(monkeypatch):
    app = _build_app(monkeypatch)

    body = _inject(app, _page())

    assert OVERLAY_HIDDEN_MARKER in body
    assert BOOT_REVEAL_MARKER in body


def test_reveal_ships_even_when_the_board_assets_are_already_present(monkeypatch):
    """The reveal used to be injected inside the board-asset block, so a page
    that already carried live_game_board_prep_v2.js got the hiding stylesheet
    and no reveal at all -- hidden overlay, no way back."""
    app = _build_app(monkeypatch)

    body = _inject(app, _page(
        '<script src="/static/js/live_game_board_prep_v2.js"></script>'
    ))

    assert OVERLAY_HIDDEN_MARKER in body
    assert BOOT_REVEAL_MARKER in body
    assert body.count(f'id="{BOOT_REVEAL_MARKER}"') == 1


def test_injection_is_idempotent(monkeypatch):
    app = _build_app(monkeypatch)

    body = _inject(app, _inject(app, _page()))

    assert body.count(f'id="{BOOT_REVEAL_MARKER}"') == 1
    assert body.count(f'id="{OVERLAY_HIDDEN_MARKER}"') == 1


@requires_node
def test_injected_reveal_is_syntactically_valid(tmp_path, monkeypatch):
    app = _build_app(monkeypatch)
    script_path = tmp_path / 'reveal.js'
    script_path.write_text(_reveal_script(_inject(app, _page())), encoding='utf-8')

    completed = subprocess.run(
        [NODE, '--check', str(script_path)],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
