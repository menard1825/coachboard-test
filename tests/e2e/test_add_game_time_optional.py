"""Add Game says the start time is optional.

The Game Day Add Game sheet fills in today's date but leaves Time empty on
purpose -- a game can be created before its start time is known. On an
iPhone an empty time input is a blank box with no hint, so it read as broken.
The label now says the time is optional.
"""

import os

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

import cdn_assets  # noqa: E402


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'
PHONE = ('phone', {'width': 390, 'height': 844}, {'is_mobile': True, 'has_touch': True})
SMALL_PHONE = ('small-phone', {'width': 360, 'height': 740}, {'is_mobile': True, 'has_touch': True})
DESKTOP = ('desktop', {'width': 1440, 'height': 900}, {})

#: Font size and contrast of text against the modal's white background.
CONTRAST = """el => {
  const ctx = Object.assign(document.createElement('canvas'), {width: 1, height: 1}).getContext('2d');
  ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, 1, 1); ctx.fillStyle = getComputedStyle(el).color; ctx.fillRect(0, 0, 1, 1);
  const lum = rgb => { const [r, g, b] = rgb.map(v => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; }); return .2126 * r + .7152 * g + .0722 * b; };
  const fg = lum([...ctx.getImageData(0, 0, 1, 1).data].slice(0, 3));
  return {px: parseFloat(getComputedStyle(el).fontSize), contrast: 1.05 / (fg + .05)};
}"""


@pytest.fixture
def open_add_game(browser, coachboard_url):
    contexts = []

    def _open(device):
        cdn_assets.require_vendored_assets()
        _, viewport, extra = device
        context = browser.new_context(viewport=viewport, **extra)
        cdn_assets.install(context)
        contexts.append(context)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.cb_errors = errors
        page.goto(f'{coachboard_url}/login')
        page.get_by_label('Username or email').fill(TEST_USERNAME)
        page.locator('#password').fill(TEST_PASSWORD)
        page.get_by_role('button', name='Sign In').click()
        page.wait_for_load_state('load')
        page.goto(f'{coachboard_url}/game-day')
        page.locator('.gd-hero').get_by_role('button', name='Add Game').click()
        expect(page.locator('#game-day-add-modal')).to_be_visible()
        return page

    yield _open
    for context in contexts:
        context.close()


@pytest.mark.parametrize('device', [PHONE, SMALL_PHONE, DESKTOP], ids=lambda d: d[0])
def test_add_game_time_is_labelled_optional(open_add_game, device):
    page = open_add_game(device)
    modal = page.locator('#game-day-add-modal')
    label = modal.locator('label[for="gd-add-time"]')
    time = modal.locator('#gd-add-time')

    expect(label).to_have_text('Time (optional)')
    expect(page.get_by_label('Time (optional)')).to_have_attribute('id', 'gd-add-time')
    # Still empty by default, and still not required.
    expect(time).to_have_value('')
    assert not time.evaluate('el => el.required')
    # The date keeps its default.
    assert modal.locator('#gd-add-date').input_value()

    # One line, level with the Date label, and not cut off.
    geometry = label.evaluate("""el => {
      const range = document.createRange(); range.selectNodeContents(el);
      const lines = new Set([...range.getClientRects()].filter(r => r.width > 1).map(r => Math.round(r.top))).size;
      const date = document.querySelector('label[for="gd-add-date"]').getBoundingClientRect();
      const box = el.getBoundingClientRect(), input = document.getElementById('gd-add-time').getBoundingClientRect();
      return {lines, dateTop: date.top, top: box.top, fits: el.scrollWidth <= el.clientWidth + 1,
              right: box.right, inputRight: input.right};
    }""")
    assert geometry['lines'] == 1, geometry
    assert abs(geometry['top'] - geometry['dateTop']) <= 1, geometry
    assert geometry['fits'] and geometry['right'] <= geometry['inputRight'] + 1, geometry
    # "(optional)" is quieter than the label but still readable outdoors.
    hint = label.locator('span').evaluate(CONTRAST)
    assert hint['px'] >= 12 and hint['contrast'] >= 4.5, hint
    assert page.cb_errors == []

