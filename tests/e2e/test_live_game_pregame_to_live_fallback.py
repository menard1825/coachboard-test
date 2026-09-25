"""Another coach's pregame screen switches to live when the game starts.

The socket broadcast normally does it at once. When Socket.IO is unavailable,
the existing 5-second /state check in live_game_postgame_cleanup.js -- the
same one that already covers the postgame redirect -- notices the game went
live and hands that state to live_game_v2.js. No extra polling loop.
"""

import os
import re
import time

import pytest

pytestmark = pytest.mark.e2e

if os.environ.get("COACHBOARD_E2E") != "1":
    pytest.skip("Set COACHBOARD_E2E=1 to run Playwright tests.", allow_module_level=True)

from playwright.sync_api import Browser, Page, expect

from test_live_game_postgame_redirect_race import cleanup_game, coach_context, create_game, login

# The existing fallback check runs every 5 seconds.
FALLBACK_INTERVAL_S = 5
NO_SOCKET = {"blocked": ("socket.io.min.js",)}

WATCH = """
(() => {
  window.__cbLive = [];
  document.addEventListener('coachboard:live-state', event => {
    const d = event.detail || {};
    window.__cbLive.push({source: String(d.source || ''), live: Boolean(d.state?.game?.is_live), at: Date.now()});
  }, true);
})();
"""


def open_pregame(page: Page, coachboard_url: str, game_id: int):
    page.add_init_script(WATCH)
    page.goto(f"{coachboard_url}/game/{game_id}", wait_until="domcontentloaded")
    expect(page.locator("#gm-mobile-start-game")).to_be_visible(timeout=15_000)
    expect(page.locator("#cbQuickDefense")).to_be_hidden()


def track_navigations(page: Page):
    seen = []
    page.on("framenavigated", lambda frame: seen.append(frame.url) if frame == page.main_frame else None)
    return seen


def start(page: Page, coachboard_url: str, game_id: int):
    response = page.request.post(f"{coachboard_url}/api/live-game/{game_id}/start", data={})
    assert response.ok and response.json().get("status") == "success", response.text()
    return time.monotonic()


def wait_live(page: Page, timeout_ms: int):
    expect(page.locator("#cbQuickDefense")).to_be_visible(timeout=timeout_ms)
    expect(page.locator("#pregame-checklist-container")).to_be_hidden()


@pytest.fixture
def coaches(browser: Browser, coachboard_url: str):
    """Coach A (who starts games) plus a factory for Coach B contexts; every
    game made here is ended and deleted afterwards."""
    contexts, games = [], []
    a_context = coach_context(browser)
    contexts.append(a_context)
    coach_a = a_context.new_page()
    login(coach_a, coachboard_url)

    def new_game(opponent):
        game_id = create_game(coach_a, coachboard_url, opponent)
        games.append(game_id)
        return game_id

    def coach_b(**routing):
        context = coach_context(browser, **routing)
        contexts.append(context)
        page = context.new_page()
        login(page, coachboard_url)
        page.cb_context = context
        return page

    yield coach_a, coach_b, new_game
    for game_id in games:
        cleanup_game(coach_a, coachboard_url, game_id)
    for context in contexts:
        context.close()


def test_socket_moves_the_other_coach_to_live_at_once(coaches, coachboard_url):
    coach_a, coach_b, new_game = coaches
    game_id = new_game("Socket Start Opponent")
    b = coach_b()
    open_pregame(b, coachboard_url, game_id)
    expect(b.locator("#live-sync-status-v2")).to_contain_text("SYNCED", timeout=10_000)
    # Only the socket may deliver the start: block Coach B's /state checks.
    b.route(f"**/api/live-game/{game_id}/state", lambda route: route.abort())

    started = start(coach_a, coachboard_url, game_id)
    wait_live(b, 3_000)
    assert time.monotonic() - started < 3


def test_without_a_socket_the_other_coach_goes_live_within_the_fallback_interval(coaches, coachboard_url):
    coach_a, coach_b, new_game = coaches
    game_id = new_game("No Socket Start Opponent")
    b = coach_b(**NO_SOCKET)
    open_pregame(b, coachboard_url, game_id)
    assert b.evaluate("typeof io") == "undefined"
    navigations = track_navigations(b)

    started = start(coach_a, coachboard_url, game_id)
    wait_live(b, (FALLBACK_INTERVAL_S + 3) * 1000)
    assert time.monotonic() - started <= FALLBACK_INTERVAL_S + 3

    # Handed over once, in place: no reload, no navigation, no repeat.
    b.wait_for_timeout(FALLBACK_INTERVAL_S * 1000 + 1500)
    fallback = [e for e in b.evaluate("window.__cbLive") if e["source"] == "live-v2-fallback"]
    assert len(fallback) == 1, b.evaluate("window.__cbLive")
    assert navigations == [], navigations
    assert re.search(rf"/game/{game_id}/?$", b.url), b.url
    wait_live(b, 1_000)


def test_backgrounded_coach_goes_live_on_returning(coaches, coachboard_url):
    coach_a, coach_b, new_game = coaches
    game_id = new_game("Backgrounded Start Opponent")
    b = coach_b(**NO_SOCKET)
    open_pregame(b, coachboard_url, game_id)

    # Suspend Coach B's page the way a phone suspends a backgrounded app: no
    # script runs (so nothing may query this page until it resumes).
    suspended = b.cb_context.new_cdp_session(b)
    suspended.send("Debugger.enable")
    suspended.send("Debugger.pause")
    start(coach_a, coachboard_url, game_id)
    coach_a.wait_for_timeout((FALLBACK_INTERVAL_S + 1) * 1000)

    resumed_at_ms = time.time() * 1000
    suspended.send("Debugger.resume")
    suspended.send("Debugger.disable")
    wait_live(b, (FALLBACK_INTERVAL_S + 3) * 1000)

    # It went live only after coming back, not while suspended.
    went_live = [e for e in b.evaluate("window.__cbLive") if e["live"]]
    assert went_live and went_live[0]["at"] >= resumed_at_ms - 50, (resumed_at_ms, went_live)


def test_another_game_starting_leaves_the_coach_on_this_pregame(coaches, coachboard_url):
    coach_a, coach_b, new_game = coaches
    this_game = new_game("Still Pregame Opponent")
    other_game = new_game("Other Game Starts Opponent")
    b = coach_b(**NO_SOCKET)
    open_pregame(b, coachboard_url, this_game)
    navigations = track_navigations(b)

    start(coach_a, coachboard_url, other_game)
    b.wait_for_timeout((FALLBACK_INTERVAL_S + 2) * 1000)

    expect(b.locator("#gm-mobile-start-game")).to_be_visible()
    expect(b.locator("#cbQuickDefense")).to_be_hidden()
    assert not any(e["live"] for e in b.evaluate("window.__cbLive")), b.evaluate("window.__cbLive")
    assert navigations == [], navigations
