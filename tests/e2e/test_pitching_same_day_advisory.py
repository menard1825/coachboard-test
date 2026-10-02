"""Pitchers who already pitched today are not listed as "Ready to pitch".

Under Pitch Smart (12U here), pitching in a second game the same day is a
recommendation against, not a rule: a pitcher who threw 41 or 58 in a game
today is still eligible today (up to the daily maximum), with rest required
afterwards. The Pitching page's compact "Ready to pitch" list used to show
them like everyone else (walkthrough F7). They stay eligible -- the advisory
is not made a violation, and the rest dates are unchanged -- but their cards
stay in view with the advisory and the next date, the list says they are
there, and the Eligible Today tile counts them.
"""

import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

import cdn_assets  # noqa: E402
from live_field_markers import login  # noqa: E402


PITCHED = {'Left Lee': 41, 'Center Casey': 58}
DEVICES = [
    ('ipad', {'width': 1032, 'height': 1376}, {'is_mobile': True, 'has_touch': True}),
    ('phone', {'width': 440, 'height': 956}, {'is_mobile': True, 'has_touch': True}),
]


@pytest.fixture
def pitched_today(browser, coachboard_url):
    context = browser.new_context()
    cdn_assets.install(context)
    api = context.new_page()
    login(api, coachboard_url)
    # The team's competition rules: 12U Pitch Smart (restored afterwards).
    settings = f'{coachboard_url}/api/pitching-preferences/settings'
    before = api.request.get(settings).json()['settings']
    response = api.request.post(settings, data={
        'competition_default_rule': 'MLB Pitch Smart', 'arm_care_rule_set': before.get('arm_care_rule_set') or ''})
    assert response.ok, response.text()[:200]
    roster = {p['name']: p['id'] for p in api.request.get(f'{coachboard_url}/api/roster').json()}
    today = datetime.now(ZoneInfo('America/Indiana/Indianapolis')).date().isoformat()
    for name, pitches in PITCHED.items():
        response = api.request.post(f'{coachboard_url}/add_pitching', form={
            'player_id': str(roster[name]), 'pitches': str(pitches), 'pitch_date': today,
            'outing_type': 'Game', 'opponent': 'Advisory Check', 'innings_whole': '2',
            'innings_outs': '0', 'pitcher_type': 'Starter'}, max_redirects=0)
        assert response.status in (200, 302), response.text()[:200]
    yield
    api.goto(f'{coachboard_url}/pitching')
    for outing_id in api.locator('[data-outing-id]').evaluate_all(
            "els => els.filter(e => e.closest('[data-pitch-history-player]')?.textContent.includes('Advisory Check'))"
            ".map(e => e.dataset.outingId)"):
        api.request.get(f'{coachboard_url}/delete_pitching/{outing_id}', max_redirects=0)
    api.request.post(settings, data={
        'competition_default_rule': before.get('competition_default_rule') or '',
        'arm_care_rule_set': before.get('arm_care_rule_set') or ''})
    context.close()


@pytest.mark.parametrize('device', DEVICES, ids=lambda d: d[0])
def test_pitched_today_is_eligible_with_an_advisory_not_ready(browser, coachboard_url, pitched_today, device):
    _, viewport, extra = device
    context = browser.new_context(viewport=viewport, **extra)
    cdn_assets.install(context)
    page = context.new_page()
    try:
        login(page, coachboard_url)
        page.goto(f'{coachboard_url}/pitching')
        rollup = page.locator('#cb-ready-pitcher-rollup')
        expect(rollup).to_be_visible(timeout=15_000)

        names = rollup.locator('.cb-ready-rollup-name span').all_inner_texts()
        for name in PITCHED:
            assert name not in names, names
        expect(rollup.locator('.cb-ready-rollup-head small')).to_contain_text(
            '2 more eligible with an advisory, shown below')
        expect(page.locator('[data-pitch-advisory-count]')).to_have_text('2 with an advisory')

        for name, rest in (('Left Lee', 'Mon'), ('Center Casey', 'Tue')):
            card = page.locator(f'#pitcherAvailabilityCard .cb-pitcher-card[data-player-name="{name}"]')
            expect(card).to_be_visible()
            expect(card.locator('.cb-pitch-decision')).to_contain_text('Eligible Today — Advisory')
            expect(card.locator('[data-after-today]')).to_contain_text(
                re.compile(rf'Pitched today: {PITCHED[name]} game pitches · \d days? rest needed'))
        assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth + 2')
    finally:
        context.close()
