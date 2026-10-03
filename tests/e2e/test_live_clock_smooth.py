"""The header's game clock advances one second at a time between reads.

The clock counted on from each /clock read's whole seconds, so every read
(three scripts read it, every 15 s) moved the display by up to a second: a
2-second step, then a 2-second pause. It now runs from the game's start on
this device's clock, corrected only when a read shows the device clock is
off; paused and ended clocks show the server's value.
"""

import os
import time

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

from test_pregame_plan_reference import PHONE, _api, live  # noqa: E402,F401 (live is a fixture)


TIME = '#cbDugoutHeader [data-cb-clock-time]'
LABEL = '#cbDugoutHeader [data-cb-clock-label]'


def _seconds(text):
    total = 0
    for part in text.lstrip('+-').split(':'):
        total = total * 60 + int(part)
    return total


def _open(page, url):
    page.goto(f'{url}/game/{page.cb_game}')
    page.locator('#cbQuickDefense').wait_for(state='visible', timeout=20_000)
    expect(page.locator(TIME)).not_to_have_text('—', timeout=10_000)


def _server_elapsed(page, url):
    return page.cb_api.request.get(_api(page, url, 'clock')).json()['clock']['elapsed_seconds']


def test_the_clock_steps_one_second_at_a_time_across_reads(live, coachboard_url):
    page = live(PHONE)
    _open(page, coachboard_url)
    changes, last, start = [], None, time.monotonic()
    while time.monotonic() - start < 18:                 # spans the 15 s reads
        text = page.locator(TIME).text_content().strip()
        if text != last:
            changes.append((time.monotonic(), _seconds(text)))
            last = text
        page.wait_for_timeout(40)
    # From the 3rd second on: the first tick moves onto the clock's own second.
    changes = [c for c in changes if c[0] - start > 2]
    steps = [(round((b[0] - a[0]) * 1000), b[1] - a[1]) for a, b in zip(changes, changes[1:])]
    assert len(steps) >= 14, steps
    odd = [s for s in steps if abs(s[1]) != 1 or not 750 <= s[0] <= 1250]
    assert odd == [], steps


def test_a_wrong_device_clock_is_corrected(live, coachboard_url):
    page = live(PHONE)
    # This device's clock runs 45 s fast.
    page.add_init_script('(() => { const real = Date.now; Date.now = () => real() + 45000; })()')
    _open(page, coachboard_url)
    page.wait_for_timeout(1_500)
    shown = _seconds(page.locator(TIME).text_content().strip())
    assert abs(shown - _server_elapsed(page, coachboard_url)) <= 1


def test_pause_holds_the_time_and_resume_continues_it(live, coachboard_url):
    page = live(PHONE)
    api = page.cb_api.request
    assert api.post(_api(page, coachboard_url, 'clock'), data={'action': 'pause'}).ok
    _open(page, coachboard_url)
    expect(page.locator(LABEL)).to_contain_text('Paused')
    held = page.locator(TIME).text_content().strip()
    page.wait_for_timeout(2_500)
    assert page.locator(TIME).text_content().strip() == held
    assert abs(_seconds(held) - _server_elapsed(page, coachboard_url)) <= 1

    assert api.post(_api(page, coachboard_url, 'clock'), data={'action': 'resume'}).ok
    _open(page, coachboard_url)
    expect(page.locator(LABEL)).not_to_contain_text('Paused')
    resumed = _seconds(page.locator(TIME).text_content().strip())
    assert 0 <= resumed - _seconds(held) <= 2                # continues; the pause is not counted
    assert page.cb_errors == []


def test_the_clock_card_keeps_its_buttons(live, coachboard_url):
    # The card's text changes every second; its buttons are not replaced
    # (they used to be rebuilt every second, losing focus).
    page = live(PHONE)
    _open(page, coachboard_url)
    page.wait_for_function("() => document.querySelector('#cbLiveGameClock .cb-clock-config')", timeout=10_000)
    page.evaluate("() => { window.__cbClockButton = document.querySelector('#cbLiveGameClock .cb-clock-config'); }")
    before = page.locator('#cbLiveGameClock [data-cb-clock-elapsed] .cb-game-clock-time').text_content()
    page.wait_for_timeout(3_000)
    assert page.locator('#cbLiveGameClock [data-cb-clock-elapsed] .cb-game-clock-time').text_content() != before
    assert page.evaluate("() => window.__cbClockButton === document.querySelector('#cbLiveGameClock .cb-clock-config')"
                         " && window.__cbClockButton.isConnected")
