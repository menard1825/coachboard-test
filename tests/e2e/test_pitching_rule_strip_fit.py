"""The Pitching rule strip shows the whole rule name on phones.

On phones the two rule tiles sit side by side, and the value used to be cut to
one line with an ellipsis ("Select per ga…", "MLB Pitch Sm…"). It now wraps
inside its tile at the same size, and tablet and desktop keep one line.
"""

import os

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

import cdn_assets
from live_field_markers import login


# The longest rule set name the app offers.
LONGEST_RULES = 'Little League Baseball'

STRIP = r"""(label) => {
  const name = document.getElementById('pitchingCompetitionName');
  if (label) name.textContent = label;
  const box = el => el.getBoundingClientRect();
  const root = document.documentElement;
  return {
    viewport: root.clientWidth,
    overflow: root.scrollWidth - root.clientWidth,
    items: [...document.querySelectorAll('#pitchingRuleStrip .cb-pitch-rule-item')].map(item => {
      const value = item.querySelector('strong');
      const style = getComputedStyle(value);
      const lineHeight = parseFloat(style.lineHeight) || parseFloat(style.fontSize) * 1.5;
      return {
        text: value.textContent.trim(),
        clipped: value.scrollWidth > value.clientWidth || value.scrollHeight > value.clientHeight,
        ellipsis: style.textOverflow === 'ellipsis',
        insideTile: box(value).right <= box(item).right + 0.5 && box(value).bottom <= box(item).bottom + 0.5,
        fontPx: parseFloat(style.fontSize),
        lines: Math.round(box(value).height / lineHeight),
        top: Math.round(box(item).top),
        right: box(item).right,
      };
    }),
    summaryRight: Math.max(0, ...[...document.querySelectorAll('.cb-pitch-summary-item')].map(e => box(e).right)),
    cardsOverflowing: [...document.querySelectorAll('.cb-pitcher-card')].filter(c => c.scrollWidth > c.clientWidth + 1).length,
  };
}"""


def _strips(browser, coachboard_url, width):
    cdn_assets.require_vendored_assets()
    phone = width < 700
    context = browser.new_context(viewport={'width': width, 'height': 900}, is_mobile=phone, has_touch=width < 1200)
    try:
        cdn_assets.install(context)
        page = context.new_page()
        login(page, coachboard_url)
        page.goto(f'{coachboard_url}/pitching')
        # Wait for the settings request that rewrites the strip.
        page.wait_for_function("document.getElementById('pitchingArmCareName').textContent.trim() !== 'Loading…'")
        if phone:
            # ...and for the phone layout enhancer, so this is the settled layout.
            page.wait_for_function("document.body.classList.contains('cb-pitch-dugout-mobile')")
        return page.evaluate(STRIP, None), page.evaluate(STRIP, LONGEST_RULES)
    finally:
        context.close()


def _assert_fully_visible(strip):
    assert strip['overflow'] == 0, strip
    assert len(strip['items']) == 2, strip
    for item in strip['items']:
        assert item['text'] and item['text'] != 'Loading…', strip
        assert not item['clipped'] and not item['ellipsis'], item
        assert item['insideTile'] and item['right'] <= strip['viewport'], item
    assert strip['summaryRight'] <= strip['viewport'], strip
    assert strip['cardsOverflowing'] == 0, strip


@pytest.mark.parametrize('width', [360, 390])
def test_phone_rule_strip_shows_the_whole_rule_name(browser, coachboard_url, width):
    for strip in _strips(browser, coachboard_url, width):
        _assert_fully_visible(strip)
        competition, arm_care = strip['items']
        assert abs(competition['top'] - arm_care['top']) <= 2, strip   # still side by side
        for item in strip['items']:
            assert item['fontPx'] >= 12, item                          # not shrunk to fit
            assert item['lines'] <= 2, item


@pytest.mark.parametrize('width', [768, 1024, 1280])
def test_tablet_and_desktop_rule_strip_stay_on_one_line(browser, coachboard_url, width):
    for strip in _strips(browser, coachboard_url, width):
        _assert_fully_visible(strip)
        assert [item['lines'] for item in strip['items']] == [1, 1], strip
