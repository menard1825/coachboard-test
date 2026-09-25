"""Postgame navigation for every coach viewing a live game.

When a live game ends, the coach who ended it goes to the Game Report, and
every other coach/device on that same game follows automatically:
live_game_postgame_cleanup.js redirects on the server's game_state_update
broadcast (live_game_v2.js republishes it as coachboard:live-state), with a
slow /state check as the fallback when the socket is unavailable. It only
redirects once it has seen this game live and the durable End Game marker is
present, so a stale pre-start is_live=false response cannot end the game.

Every coach here gets its own browser context with the vendored CDN assets
routed (see cdn_assets.py); without socket.io the other coach never hears the
live broadcast at all.
"""

import json
import os
import re
from datetime import date, timedelta

import pytest

pytestmark = pytest.mark.e2e

if os.environ.get("COACHBOARD_E2E") != "1":
    pytest.skip(
        "Set COACHBOARD_E2E=1 to run Playwright tests.",
        allow_module_level=True,
    )

from playwright.sync_api import Browser, Page, expect

import cdn_assets


TEST_USERNAME = "playwright-coach"
TEST_PASSWORD = "playwright-password"


def login(page: Page, coachboard_url: str):
    page.goto(f"{coachboard_url}/login")
    page.get_by_label("Username or email").fill(TEST_USERNAME)
    page.locator("#password").fill(TEST_PASSWORD)
    page.get_by_role("button", name="Sign In").click()

    expect(page).to_have_url(
        re.compile(
            rf"^{re.escape(coachboard_url)}/?"
            rf"(?:#(?:overview|games))?$"
        )
    )


def alignment():
    return {
        "P": "Pitcher Pat",
        "C": "Catcher Cole",
        "1B": "First Frank",
        "2B": "Second Sam",
        "3B": "Third Theo",
        "SS": "Shortstop Shawn",
        "LF": "Left Lee",
        "CF": "Center Casey",
        "RF": "Right Riley",
    }


def create_game(page: Page, coachboard_url: str, opponent: str):
    response = page.request.post(
        f"{coachboard_url}/game-day/add",
        form={
            "game_date": (
                date.today() + timedelta(days=14)
            ).isoformat(),
            "game_start_time": "12:30",
            "game_opponent": opponent,
            "game_location": "Postgame Race Test Field",
            "game_notes": "Disposable postgame redirect race test",
            "pitching_rule_set": "USSSA",
        },
        max_redirects=0,
    )

    assert response.status in {302, 303}

    match = re.search(
        r"/game/(\d+)",
        response.headers.get("location") or "",
    )
    assert match

    game_id = int(match.group(1))

    rotation = page.request.post(
        f"{coachboard_url}/save_rotation",
        data={
            "title": f"{opponent} Rotation",
            "innings": {"1": alignment()},
            "associated_game_id": game_id,
        },
    )

    assert rotation.status == 200
    assert rotation.json().get("status") == "success"

    return game_id


def coach_context(browser: Browser, **routing):
    """A phone-sized browser context for one coach, with CDN assets served."""
    cdn_assets.require_vendored_assets()
    context = browser.new_context(viewport={"width": 390, "height": 844})
    cdn_assets.install(context, **routing)
    return context


def cleanup_game(page: Page, coachboard_url: str, game_id: int):
    state = page.request.get(
        f"{coachboard_url}/api/live-game/{game_id}/state"
    )

    if (
        state.ok
        and state.json().get("game", {}).get("is_live")
    ):
        page.request.post(
            f"{coachboard_url}/api/live-game/"
            f"{game_id}/end-with-pitching",
            data={
                "defer_pitching": True,
                "end_reason": "manual",
                "current_inning_played": True,
            },
        )

    page.request.post(
        f"{coachboard_url}/game-day/{game_id}/delete",
        headers={"Accept": "application/json"},
    )


def install_held_postgame_poll(page: Page):
    page.add_init_script(
        """
        (() => {
          const realFetch = window.fetch.bind(window);

          let releaseHeld = null;

          window.__cbPostgameRace = {
            heldReady: false,
            heldBody: null,
            heldStack: null,
            released: false,
            liveEvents: [],
          };

          document.addEventListener(
            'coachboard:live-state',
            event => {
              const state = event?.detail?.state || null;

              window.__cbPostgameRace.liveEvents.push({
                source: String(
                  event?.detail?.source || ''
                ),
                isLive: Boolean(
                  state?.game?.is_live
                ),
              });
            },
            true
          );

          window.__releaseHeldPostgameState = () => {
            if (releaseHeld) releaseHeld();
          };

          window.fetch = async (...args) => {
            const input = args[0];

            const url =
              typeof input === 'string'
                ? input
                : String(input?.url || '');

            const stack =
              (new Error('fetch-trace')).stack || '';

            const isState =
              url.includes('/api/live-game/') &&
              url.endsWith('/state');

            const isPostgamePoll =
              stack.includes(
                'live_game_postgame_cleanup'
              ) &&
              stack.includes('checkState');

            if (
              isState &&
              isPostgamePoll &&
              !window.__cbPostgameRace.heldReady
            ) {
              const response =
                await realFetch(...args);

              const body =
                await response.clone().text();

              window.__cbPostgameRace.heldReady = true;
              window.__cbPostgameRace.heldBody = body;
              window.__cbPostgameRace.heldStack = stack;

              await new Promise(resolve => {
                releaseHeld = resolve;
              });

              window.__cbPostgameRace.released = true;

              return new Response(
                body,
                {
                  status: response.status,
                  statusText: response.statusText,
                  headers: response.headers,
                }
              );
            }

            return realFetch(...args);
          };
        })();
        """
    )


def test_stale_prestart_false_state_does_not_redirect_after_live(
    browser: Browser,
    coachboard_url: str,
):
    coach_a_context = coach_context(browser)
    coach_b_context = coach_context(browser)

    coach_a = coach_a_context.new_page()
    coach_b = coach_b_context.new_page()
    game_id = None

    try:
        login(coach_a, coachboard_url)
        login(coach_b, coachboard_url)

        game_id = create_game(
            coach_a,
            coachboard_url,
            "Stale State Regression Opponent",
        )

        install_held_postgame_poll(coach_b)

        coach_a.goto(
            f"{coachboard_url}/game/{game_id}",
            wait_until="domcontentloaded",
        )

        coach_b.goto(
            f"{coachboard_url}/game/{game_id}",
            wait_until="domcontentloaded",
        )

        coach_b.wait_for_function(
            "() => Boolean("
            "window.__cbPostgameRace?.heldReady"
            ")",
            timeout=10_000,
        )

        held = coach_b.evaluate(
            """
            () => ({
              body:
                window.__cbPostgameRace.heldBody,
              stack:
                window.__cbPostgameRace.heldStack,
            })
            """
        )

        held_state = json.loads(held["body"])

        assert (
            held_state.get("game", {}).get("is_live")
            is False
        )

        assert not any(
            event.get("event_type") == "End Game"
            and not event.get("reverted")
            for event in held_state.get(
                "rotation_events",
                [],
            )
        )

        assert "live_game_postgame_cleanup" in held["stack"]
        assert "checkState" in held["stack"]

        expect(
            coach_a.locator("#live-sync-status-v2")
        ).to_contain_text(
            "SYNCED",
            timeout=10_000,
        )

        expect(
            coach_b.locator("#live-sync-status-v2")
        ).to_contain_text(
            "SYNCED",
            timeout=10_000,
        )

        start = coach_a.locator("#gm-mobile-start-game")
        expect(start).to_be_visible(timeout=15_000)
        start.click()

        expect(
            coach_a.locator("#cbQuickDefense")
        ).to_be_visible(timeout=15_000)

        coach_b.wait_for_function(
            """
            () =>
              (window.__cbPostgameRace?.liveEvents || [])
                .some(item => item.isLive === true)
            """,
            timeout=15_000,
        )

        assert re.search(
            rf"/game/{game_id}/?$",
            coach_b.url,
        ), coach_b.url

        coach_b.evaluate(
            "() => window.__releaseHeldPostgameState()"
        )

        coach_b.wait_for_function(
            "() => window.__cbPostgameRace?.released === true",
            timeout=5_000,
        )

        # The stale false response has now been consumed. The redirect
        # decision runs synchronously from that response, so a short
        # settling window is sufficient to prove it did not fire.
        coach_b.wait_for_timeout(750)

        assert re.search(
            rf"/game/{game_id}/?$",
            coach_b.url,
        ), (
            "A stale pre-start false state incorrectly redirected "
            f"Coach B to {coach_b.url}"
        )

        expect(
            coach_b.locator("#cbQuickDefense")
        ).to_be_visible(timeout=5_000)

    finally:
        if game_id is not None:
            cleanup_game(
                coach_a,
                coachboard_url,
                game_id,
            )

        coach_a_context.close()
        coach_b_context.close()


def test_real_end_game_marker_redirects_secondary_coach(
    browser: Browser,
    coachboard_url: str,
):
    coach_a_context = coach_context(browser)
    coach_b_context = coach_context(browser)

    coach_a = coach_a_context.new_page()
    coach_b = coach_b_context.new_page()
    game_id = None

    try:
        login(coach_a, coachboard_url)
        login(coach_b, coachboard_url)

        game_id = create_game(
            coach_a,
            coachboard_url,
            "Real End Game Regression Opponent",
        )

        coach_a.goto(
            f"{coachboard_url}/game/{game_id}",
            wait_until="domcontentloaded",
        )

        coach_b.goto(
            f"{coachboard_url}/game/{game_id}",
            wait_until="domcontentloaded",
        )

        expect(
            coach_a.locator("#live-sync-status-v2")
        ).to_contain_text(
            "SYNCED",
            timeout=10_000,
        )

        expect(
            coach_b.locator("#live-sync-status-v2")
        ).to_contain_text(
            "SYNCED",
            timeout=10_000,
        )

        start = coach_a.locator("#gm-mobile-start-game")
        expect(start).to_be_visible(timeout=15_000)
        start.click()

        expect(
            coach_a.locator("#cbQuickDefense")
        ).to_be_visible(timeout=15_000)

        expect(
            coach_b.locator("#cbQuickDefense")
        ).to_be_visible(timeout=15_000)

        ended = coach_a.request.post(
            f"{coachboard_url}/api/live-game/"
            f"{game_id}/end-with-pitching",
            data={
                "defer_pitching": True,
                "end_reason": "manual",
                "current_inning_played": True,
            },
        )

        assert ended.status == 200
        payload = ended.json()
        assert payload.get("status") == "success"

        state = payload["state"]

        assert state["game"]["is_live"] is False

        assert any(
            event.get("event_type") == "End Game"
            and not event.get("reverted")
            for event in state.get(
                "rotation_events",
                [],
            )
        )

        expect(coach_b).to_have_url(
            re.compile(
                rf"^{re.escape(coachboard_url)}"
                rf"/game-day/{game_id}/report$"
            ),
            timeout=15_000,
        )

        expect(
            coach_b.get_by_text(
                "Game Report",
                exact=True,
            )
        ).to_be_visible()

    finally:
        if game_id is not None:
            cleanup_game(
                coach_a,
                coachboard_url,
                game_id,
            )

        coach_a_context.close()
        coach_b_context.close()


# --- Every coach on the game follows the end of it ---------------------------

END_GAME = {"defer_pitching": True, "end_reason": "manual", "current_inning_played": True}


def report_url(coachboard_url, game_id):
    return re.compile(rf"^{re.escape(coachboard_url)}/game-day/{game_id}/report$")


def open_live(page: Page, coachboard_url: str, game_id: int):
    page.goto(f"{coachboard_url}/game/{game_id}", wait_until="domcontentloaded")
    expect(page.locator("#cbQuickDefense")).to_be_visible(timeout=15_000)
    expect(page.locator("#live-sync-status-v2")).to_contain_text("SYNCED", timeout=10_000)


def track_report_visits(page: Page, coachboard_url: str, game_id: int):
    """Count main-frame navigations to this game's report."""
    visits = []
    pattern = report_url(coachboard_url, game_id)
    page.on("framenavigated", lambda frame: visits.append(frame.url)
            if frame == page.main_frame and pattern.match(frame.url) else None)
    return visits


def start_game(page: Page, coachboard_url: str, opponent: str):
    game_id = create_game(page, coachboard_url, opponent)
    started = page.request.post(f"{coachboard_url}/api/live-game/{game_id}/start", data={})
    assert started.ok and started.json().get("status") == "success", started.text()
    return game_id


def test_end_game_takes_the_ending_coach_and_the_other_coach_to_the_report(
    browser: Browser,
    coachboard_url: str,
):
    coach_a_context = coach_context(browser)
    coach_b_context = coach_context(browser)
    coach_a, coach_b = coach_a_context.new_page(), coach_b_context.new_page()
    game_id = None

    try:
        login(coach_a, coachboard_url)
        login(coach_b, coachboard_url)
        game_id = start_game(coach_a, coachboard_url, "Both Coaches Opponent")
        open_live(coach_a, coachboard_url, game_id)
        open_live(coach_b, coachboard_url, game_id)
        b_visits = track_report_visits(coach_b, coachboard_url, game_id)

        # Coach A ends the game the way a coach does: End Game, then confirm.
        coach_a.once("dialog", lambda dialog: dialog.accept())
        coach_a.locator("#liveEndGameBtn").click()

        expect(coach_a).to_have_url(report_url(coachboard_url, game_id), timeout=10_000)
        expect(coach_a.get_by_text("Game Report", exact=True)).to_be_visible()

        expect(coach_b).to_have_url(report_url(coachboard_url, game_id), timeout=10_000)
        expect(coach_b.get_by_text("Game Report", exact=True)).to_be_visible()

        # One redirect, then it stays: wait past the 5s fallback check.
        coach_b.wait_for_timeout(6_000)
        assert report_url(coachboard_url, game_id).match(coach_b.url), coach_b.url
        assert len(b_visits) == 1, b_visits
    finally:
        if game_id is not None:
            cleanup_game(coach_a, coachboard_url, game_id)
        coach_a_context.close()
        coach_b_context.close()


def test_backgrounded_coach_goes_to_the_report_on_returning(
    browser: Browser,
    coachboard_url: str,
):
    coach_a_context = coach_context(browser)
    coach_b_context = coach_context(browser)
    coach_a, coach_b = coach_a_context.new_page(), coach_b_context.new_page()
    game_id = None

    try:
        login(coach_a, coachboard_url)
        login(coach_b, coachboard_url)
        game_id = start_game(coach_a, coachboard_url, "Backgrounded Coach Opponent")
        open_live(coach_b, coachboard_url, game_id)
        b_visits = track_report_visits(coach_b, coachboard_url, game_id)

        # Suspend Coach B's page the way a phone suspends a backgrounded
        # app: no script runs -- no timers, no socket handlers, no
        # navigation -- while the game ends.
        suspended = coach_b_context.new_cdp_session(coach_b)
        suspended.send("Debugger.enable")
        suspended.send("Debugger.pause")
        ended = coach_a.request.post(
            f"{coachboard_url}/api/live-game/{game_id}/end-with-pitching", data=END_GAME)
        assert ended.ok and ended.json()["state"]["game"]["is_live"] is False
        coach_a.wait_for_timeout(6_000)   # past a socket update and a fallback check
        assert re.search(rf"/game/{game_id}/?$", coach_b.url), coach_b.url

        suspended.send("Debugger.resume")
        suspended.send("Debugger.disable")
        expect(coach_b).to_have_url(report_url(coachboard_url, game_id), timeout=10_000)
        coach_b.wait_for_timeout(6_000)
        assert len(b_visits) == 1, b_visits
    finally:
        if game_id is not None:
            cleanup_game(coach_a, coachboard_url, game_id)
        coach_a_context.close()
        coach_b_context.close()


def test_other_coach_without_a_socket_still_reaches_the_report(
    browser: Browser,
    coachboard_url: str,
):
    """socket.io unavailable (blocked network, failed CDN): the slow /state
    check is the only path left, and it must still finish the transition."""
    coach_a_context = coach_context(browser)
    coach_b_context = coach_context(browser, blocked=("socket.io.min.js",))
    coach_a, coach_b = coach_a_context.new_page(), coach_b_context.new_page()
    game_id = None

    try:
        login(coach_a, coachboard_url)
        login(coach_b, coachboard_url)
        game_id = start_game(coach_a, coachboard_url, "No Socket Opponent")
        coach_b.goto(f"{coachboard_url}/game/{game_id}", wait_until="domcontentloaded")
        assert coach_b.evaluate("typeof io") == "undefined"
        # Let the fallback check see the game live before it ends.
        coach_b.wait_for_timeout(6_000)

        ended = coach_a.request.post(
            f"{coachboard_url}/api/live-game/{game_id}/end-with-pitching", data=END_GAME)
        assert ended.ok
        expect(coach_b).to_have_url(report_url(coachboard_url, game_id), timeout=12_000)
    finally:
        if game_id is not None:
            cleanup_game(coach_a, coachboard_url, game_id)
        coach_a_context.close()
        coach_b_context.close()


def test_coach_on_another_game_is_not_redirected(
    browser: Browser,
    coachboard_url: str,
):
    coach_a_context = coach_context(browser)
    coach_c_context = coach_context(browser)
    coach_a, coach_c = coach_a_context.new_page(), coach_c_context.new_page()
    ended_game = other_game = None

    try:
        login(coach_a, coachboard_url)
        login(coach_c, coachboard_url)
        ended_game = start_game(coach_a, coachboard_url, "Ended Game Opponent")
        other_game = start_game(coach_a, coachboard_url, "Still Live Opponent")
        open_live(coach_c, coachboard_url, other_game)

        ended = coach_a.request.post(
            f"{coachboard_url}/api/live-game/{ended_game}/end-with-pitching", data=END_GAME)
        assert ended.ok and ended.json()["state"]["game"]["is_live"] is False

        # Past the 5s fallback check: Coach C is still on the live game.
        coach_c.wait_for_timeout(6_500)
        assert re.search(rf"/game/{other_game}/?$", coach_c.url), coach_c.url
        expect(coach_c.locator("#cbQuickDefense")).to_be_visible()
    finally:
        for game_id in (ended_game, other_game):
            if game_id is not None:
                cleanup_game(coach_a, coachboard_url, game_id)
        coach_a_context.close()
        coach_c_context.close()
