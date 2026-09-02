from pathlib import Path


base = Path('templates/base.html')
text = base.read_text()
old_route = "{% set cb_primary_nav_route = request.path in ['/', '/game-day', '/game-day/'] %}"
new_route = "{% set cb_primary_nav_route = request.path in ['/', '/game-day', '/game-day/', '/pitching'] %}"
assert text.count(old_route) == 1, 'Expected one primary mobile-nav route declaration'
text = text.replace(old_route, new_route, 1)

old_more = '''<li class="nav-item flex-fill"><a class="nav-link text-center" data-cb-mobile-section="more" href="{% if request.path == '/' %}#more{% else %}{{ url_for('home') }}#more{% endif %}"><i class="bi bi-three-dots d-block"></i><span>More</span></a></li>'''
new_more = '''<li class="nav-item flex-fill"><a class="nav-link text-center{% if request.path == '/pitching' %} active{% endif %}" data-cb-mobile-section="more" href="{% if request.path == '/' %}#more{% else %}{{ url_for('home') }}#more{% endif %}"{% if request.path == '/pitching' %} aria-current="page"{% endif %}><i class="bi bi-three-dots d-block"></i><span>More</span></a></li>'''
assert text.count(old_more) == 1, 'Expected one mobile More nav item'
base.write_text(text.replace(old_more, new_more, 1))

mobile = Path('static/js/pitching_dugout_mobile.js')
text = mobile.read_text()
old_fn = '''  function ensureBottomCollapse(card) {
    if (card.querySelector('.cb-pitcher-collapse-bottom')) return;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'cb-pitcher-collapse-bottom';
    button.setAttribute('aria-expanded', 'false');
    button.innerHTML = '<span>Collapse details</span><i class="bi bi-chevron-up" aria-hidden="true"></i>';
    const target = card.querySelector('.cb-pitch-target');
    if (target) target.insertAdjacentElement('afterend', button);
    else card.appendChild(button);
  }
'''
new_fn = '''  function syncBottomCollapse(card, mobile = isMobile()) {
    const existing = card.querySelector('.cb-pitcher-collapse-bottom');
    if (!mobile) {
      existing?.remove();
      return;
    }
    if (existing) return;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'cb-pitcher-collapse-bottom';
    button.setAttribute('aria-expanded', 'false');
    button.innerHTML = '<span>Collapse details</span><i class="bi bi-chevron-up" aria-hidden="true"></i>';
    const target = card.querySelector('.cb-pitch-target');
    if (target) target.insertAdjacentElement('afterend', button);
    else card.appendChild(button);
  }
'''
assert text.count(old_fn) == 1, 'Expected one bottom collapse helper'
text = text.replace(old_fn, new_fn, 1)
assert text.count('      ensureBottomCollapse(card);') == 1, 'Expected one bottom collapse setup call'
text = text.replace('      ensureBottomCollapse(card);', '      syncBottomCollapse(card);', 1)

old_responsive = "    document.querySelectorAll('.cb-pitcher-card').forEach(card => compactStatus(card, mobile));"
new_responsive = "    document.querySelectorAll('.cb-pitcher-card').forEach(card => {\n      compactStatus(card, mobile);\n      syncBottomCollapse(card, mobile);\n    });"
assert text.count(old_responsive) == 1, 'Expected one responsive pitcher-card pass'
text = text.replace(old_responsive, new_responsive, 1)

old_click = "      if (!button) return;\n      const card = button.closest('.cb-pitcher-card');"
new_click = "      if (!button || !isMobile()) return;\n      const card = button.closest('.cb-pitcher-card');"
assert text.count(old_click) == 1, 'Expected one details-control click guard'
mobile.write_text(text.replace(old_click, new_click, 1))

tests = Path('tests/e2e/test_pitching_ux.py')
text = tests.read_text()
marker = 'def test_pitching_mobile_has_working_primary_navigation'
assert marker not in text, 'Pitching navigation regression tests already present'
addition = r'''


def test_pitching_mobile_has_working_primary_navigation(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    page.goto(f'{coachboard_url}/pitching', wait_until='domcontentloaded')

    nav = page.locator('#cb-global-mobile-nav')
    expect(nav).to_be_visible(timeout=10_000)
    home = nav.locator('[data-cb-mobile-section="overview"]')
    more = nav.locator('[data-cb-mobile-section="more"]')
    expect(home).to_be_visible()
    expect(more).to_be_visible()
    expect(more).to_have_class(re.compile(r'\bactive\b'))
    expect(more).to_have_attribute('aria-current', 'page')

    home.click()
    expect(page).to_have_url(re.compile(rf'^{re.escape(coachboard_url)}/?#overview$'))


def test_pitching_desktop_does_not_render_mobile_only_collapse_button(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 1440, 'height': 900})
    login(page, coachboard_url)
    page.goto(f'{coachboard_url}/pitching', wait_until='domcontentloaded')

    cards = page.locator('.cb-pitcher-card')
    expect(cards).not_to_have_count(0)
    page.wait_for_function('() => window.CoachBoardPitchingDugoutMobile?.initialized === true')
    expect(cards.first.locator('.cb-pitch-metrics')).to_be_visible()
    expect(page.locator('.cb-pitcher-collapse-bottom')).to_have_count(0)
'''
tests.write_text(text.rstrip() + addition + '\n')

print('Pitching navigation/detail-control patch applied.')
