"""A Home refresh never wipes unsaved Roster or Development edits.

`data_updated` (any coach's change anywhere) makes main.js refetch the open
Home section and rebuild it with innerHTML. That used to collapse the open
Roster card and throw away anything typed or picked in its editor, and wipe
a player's unsaved lesson info on Development. Unsaved values are now carried
over to the same player; untouched fields still take the refreshed values.
"""

import os
import uuid

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

import cdn_assets  # noqa: E402
from e2e_cleanup import delete_players_named  # noqa: E402


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'
DESKTOP = {'width': 1440, 'height': 900}
PHONE = {'width': 390, 'height': 844}
FETCHED = "performance.getEntriesByType('resource').filter(e => e.name.includes('{api}')).length"


@pytest.fixture
def home(browser, coachboard_url):
    """Logged-in pages plus players this test owns (removed afterwards)."""
    contexts, names = [], []

    def open_page(viewport=DESKTOP):
        cdn_assets.require_vendored_assets()
        mobile = viewport is PHONE
        context = browser.new_context(viewport=viewport, is_mobile=mobile, has_touch=mobile)
        cdn_assets.install(context)
        contexts.append(context)
        page = context.new_page()
        page.cb_errors = []
        page.on('pageerror', lambda error: page.cb_errors.append(str(error)))
        page.goto(f'{coachboard_url}/login')
        page.get_by_label('Username or email').fill(TEST_USERNAME)
        page.locator('#password').fill(TEST_PASSWORD)
        page.get_by_role('button', name='Sign In').click()
        page.wait_for_load_state('load')
        return page

    api = open_page()

    def new_player(label, number, notes=''):
        name = f'{label} {uuid.uuid4().hex[:4]}'
        response = api.request.post(f'{coachboard_url}/add_player', form={
            'name': name, 'number': number, 'position1': 'SS', 'position2': '', 'position3': '',
            'throws': 'Right', 'bats': 'Right', 'notes': notes, 'pitcher_role': 'Not a Pitcher',
            'roster_status': 'regular'}, headers={'X-Requested-With': 'XMLHttpRequest'})
        assert response.ok and response.json().get('status') == 'success', response.text()
        names.append(name)
        player = next(p for p in api.request.get(f'{coachboard_url}/api/roster').json() if p['name'] == name)
        return player

    yield open_page, new_player, api
    delete_players_named(api.request, coachboard_url, names)
    for context in contexts:
        context.close()


def refresh_from_elsewhere(page, api, base_url, dataset, times=1):
    """Another coach's change: emits data_updated; the open section rebuilds."""
    for _ in range(times):
        before = page.evaluate(FETCHED.format(api=dataset))
        response = api.request.post(f'{base_url}/add_note/team_notes',
                                    form={'note_text': f'Elsewhere {uuid.uuid4().hex[:6]}'})
        assert response.status in (200, 302)
        page.wait_for_function(f'{FETCHED.format(api=dataset)} > {before}', timeout=15_000)
        page.wait_for_timeout(600)


def update_player(api, base_url, player, **changes):
    fields = {k: player.get(k) or '' for k in ('name', 'number', 'position1', 'position2', 'position3',
                                                'throws', 'bats', 'notes', 'pitcher_role')}
    fields['roster_status'] = 'guest' if player.get('is_guest') else 'regular'
    fields.update(changes)
    response = api.request.post(f'{base_url}/update_player_inline/{player["id"]}', form=fields)
    assert response.ok and response.json().get('status') == 'success', response.text()


# --- Roster ------------------------------------------------------------------

def show_roster(page, base_url):
    page.goto(f'{base_url}/#roster')
    expect(page.locator('#roster-cards-container .player-card').first).to_be_visible(timeout=15_000)


def open_card(page, player):
    card = page.locator(f'#collapse-roster-{player["id"]}')
    page.locator(f'[href="#collapse-roster-{player["id"]}"]').click()
    expect(card).to_be_visible()
    page.wait_for_timeout(400)
    return card


def test_unsaved_roster_edits_survive_a_refresh_on_their_own_player(home, coachboard_url):
    open_page, new_player, api = home
    a = new_player('Roster A', '41', notes='Saved notes A')
    b = new_player('Roster B', '42', notes='Saved notes B')
    page = open_page()
    show_roster(page, coachboard_url)
    card_b = open_card(page, b)
    card_a = open_card(page, a)

    card_a.locator('[name="name"]').fill(f'{a["name"]} Jr')
    card_a.locator('[name="number"]').fill('7')
    card_a.locator('[name="throws"]').select_option('Left')
    card_a.locator('[name="pitcher_role"]').select_option('Reliever')
    notes = card_a.locator('[name="notes"]')
    notes.fill('Unsaved: sore shoulder, no long toss')
    notes.focus()
    notes.evaluate('el => el.setSelectionRange(9, 9)')

    refresh_from_elsewhere(page, api, coachboard_url, '/api/roster')

    card_a = page.locator(f'#collapse-roster-{a["id"]}')
    expect(card_a).to_be_visible()
    expect(card_a.locator('[name="name"]')).to_have_value(f'{a["name"]} Jr')
    expect(card_a.locator('[name="number"]')).to_have_value('7')
    expect(card_a.locator('[name="throws"]')).to_have_value('Left')
    expect(card_a.locator('[name="pitcher_role"]')).to_have_value('Reliever')
    expect(card_a.locator('[name="notes"]')).to_have_value('Unsaved: sore shoulder, no long toss')
    # Player B keeps its own values.
    card_b = page.locator(f'#collapse-roster-{b["id"]}')
    expect(card_b).to_be_visible()
    expect(card_b.locator('[name="name"]')).to_have_value(b['name'])
    expect(card_b.locator('[name="number"]')).to_have_value('42')
    expect(card_b.locator('[name="notes"]')).to_have_value('Saved notes B')
    expect(card_b.locator('[name="throws"]')).to_have_value('Right')
    # Still typing where the coach was.
    focus = page.evaluate("""() => ({card: document.activeElement?.closest('[id^="collapse-roster-"]')?.id,
      name: document.activeElement?.name, start: document.activeElement?.selectionStart})""")
    assert focus == {'card': f'collapse-roster-{a["id"]}', 'name': 'notes', 'start': 9}, focus
    page.keyboard.type('*')
    expect(card_a.locator('[name="notes"]')).to_have_value('Unsaved: *sore shoulder, no long toss')
    assert page.cb_errors == []


def test_untouched_roster_fields_take_remote_changes(home, coachboard_url):
    open_page, new_player, api = home
    a = new_player('Remote Roster', '43', notes='Old notes')
    page = open_page()
    show_roster(page, coachboard_url)
    card = open_card(page, a)
    card.locator('[name="number"]').fill('9')

    update_player(api, coachboard_url, a, notes='Notes from another coach', bats='Left')
    page.wait_for_timeout(1500)

    card = page.locator(f'#collapse-roster-{a["id"]}')
    expect(card.locator('[name="notes"]')).to_have_value('Notes from another coach')
    expect(card.locator('[name="bats"]')).to_have_value('Left')
    expect(card.locator('[name="number"]')).to_have_value('9')


def test_after_save_player_later_roster_updates_show(home, coachboard_url):
    open_page, new_player, api = home
    a = new_player('Save Roster', '44')
    page = open_page()
    show_roster(page, coachboard_url)
    card = open_card(page, a)
    card.locator('[name="notes"]').fill('Saved by this coach')
    with page.expect_response(lambda r: '/update_player_inline/' in r.url) as saved_response:
        card.locator('.save-player-btn').click()
    assert saved_response.value.ok
    saved = next(p for p in api.request.get(f'{coachboard_url}/api/roster').json() if p['id'] == a['id'])
    assert saved['notes'] == 'Saved by this coach'
    page.wait_for_timeout(1500)

    update_player(api, coachboard_url, saved, notes='Then changed by another coach')
    expect(page.locator(f'#collapse-roster-{a["id"]} [name="notes"]')).to_have_value(
        'Then changed by another coach', timeout=10_000)


def test_repeated_roster_refreshes_keep_one_card_and_one_save(home, coachboard_url):
    open_page, new_player, api = home
    a = new_player('Repeat Roster', '45')
    page = open_page(PHONE)
    show_roster(page, coachboard_url)
    cards_before = page.locator('#roster-cards-container .player-card').count()
    card = open_card(page, a)
    card.locator('[name="notes"]').fill('Still here after three refreshes')

    refresh_from_elsewhere(page, api, coachboard_url, '/api/roster', times=3)

    assert page.locator('#roster-cards-container .player-card').count() == cards_before
    assert page.locator(f'#collapse-roster-{a["id"]}').count() == 1
    expect(page.locator(f'#collapse-roster-{a["id"]} [name="notes"]')).to_have_value('Still here after three refreshes')
    saves = []
    page.on('request', lambda r: saves.append(r.url) if '/update_player_inline/' in r.url else None)
    with page.expect_response(lambda r: '/update_player_inline/' in r.url) as saved_response:
        page.locator(f'#collapse-roster-{a["id"]} .save-player-btn').click()
    assert saved_response.value.ok
    page.wait_for_timeout(1500)
    assert len(saves) == 1, saves
    saved = next(p for p in api.request.get(f'{coachboard_url}/api/roster').json() if p['id'] == a['id'])
    assert saved['notes'] == 'Still here after three refreshes'
    assert page.cb_errors == []


def test_a_player_deleted_elsewhere_is_not_brought_back(home, coachboard_url):
    open_page, new_player, api = home
    a = new_player('Deleted Roster', '46')
    page = open_page()
    show_roster(page, coachboard_url)
    card = open_card(page, a)
    card.locator('[name="notes"]').fill('Typed before it was deleted')

    api.request.get(f'{coachboard_url}/delete_player/{a["id"]}')
    page.wait_for_timeout(1500)

    expect(page.locator(f'#collapse-roster-{a["id"]}')).to_have_count(0)
    expect(page.locator('#roster-cards-container')).not_to_contain_text(a['name'])
    assert all(p['id'] != a['id'] for p in api.request.get(f'{coachboard_url}/api/roster').json())


# --- Development -------------------------------------------------------------

def show_player_development(page, base_url, player):
    page.goto(f'{base_url}/#player_development')
    item = page.locator(f'#dev-player-list [data-player-name="{player["name"]}"]')
    expect(item).to_be_visible(timeout=15_000)
    item.click()
    form = page.locator(f'#player-dev-content form[action="/update_lesson_info/{player["id"]}"]')
    expect(form).to_be_visible()
    return form


def lesson_form(page, player):
    return page.locator(f'#player-dev-content form[action="/update_lesson_info/{player["id"]}"]')


def test_unsaved_lesson_info_survives_a_refresh(home, coachboard_url):
    open_page, new_player, api = home
    a = new_player('Lessons A', '51')
    page = open_page()
    form = show_player_development(page, coachboard_url, a)
    form.locator('[name="has_lessons"]').select_option('Yes')
    focus_field = form.locator('[name="lesson_focus"]')
    focus_field.fill('Stay closed, then rotate')
    focus_field.focus()
    focus_field.evaluate('el => el.setSelectionRange(4, 4)')

    refresh_from_elsewhere(page, api, coachboard_url, '/api/player_development', times=2)

    form = lesson_form(page, a)
    expect(form).to_have_count(1)
    expect(form.locator('[name="lesson_focus"]')).to_have_value('Stay closed, then rotate')
    expect(form.locator('[name="has_lessons"]')).to_have_value('Yes')
    focus = page.evaluate("""() => ({form: document.activeElement?.form?.getAttribute('action'),
      name: document.activeElement?.name, start: document.activeElement?.selectionStart})""")
    assert focus == {'form': f'/update_lesson_info/{a["id"]}', 'name': 'lesson_focus', 'start': 4}, focus
    assert page.cb_errors == []


def test_lesson_text_never_lands_on_another_player(home, coachboard_url):
    open_page, new_player, api = home
    a = new_player('Lessons From', '52')
    b = new_player('Lessons To', '53')
    page = open_page()
    form = show_player_development(page, coachboard_url, a)
    form.locator('[name="lesson_focus"]').fill('Only for player A')

    page.locator(f'#dev-player-list [data-player-name="{b["name"]}"]').click()
    expect(lesson_form(page, b)).to_be_visible()
    refresh_from_elsewhere(page, api, coachboard_url, '/api/player_development')

    expect(lesson_form(page, b).locator('[name="lesson_focus"]')).to_have_value('')
    expect(lesson_form(page, b).locator('[name="has_lessons"]')).to_have_value('No')


def test_untouched_lesson_fields_take_remote_changes_and_saving_resets(home, coachboard_url):
    open_page, new_player, api = home
    a = new_player('Lessons Remote', '54')
    page = open_page()
    form = show_player_development(page, coachboard_url, a)
    form.locator('[name="has_lessons"]').select_option('Yes')

    # Another coach saves a lesson focus; this coach only changed "Taking lessons?".
    response = api.request.post(f'{coachboard_url}/update_lesson_info/{a["id"]}',
                                form={'has_lessons': 'No', 'lesson_focus': 'Remote cue'})
    assert response.status in (200, 302)
    expect(lesson_form(page, a).locator('[name="lesson_focus"]')).to_have_value('Remote cue', timeout=10_000)
    expect(lesson_form(page, a).locator('[name="has_lessons"]')).to_have_value('Yes')

    # Save, then a later remote change to the same fields shows normally.
    with page.expect_navigation():
        lesson_form(page, a).get_by_role('button', name='Save').click()
    form = show_player_development(page, coachboard_url, a)
    expect(form.locator('[name="has_lessons"]')).to_have_value('Yes')
    response = api.request.post(f'{coachboard_url}/update_lesson_info/{a["id"]}',
                                form={'has_lessons': 'No', 'lesson_focus': 'Changed after save'})
    assert response.status in (200, 302)
    expect(lesson_form(page, a).locator('[name="lesson_focus"]')).to_have_value('Changed after save', timeout=10_000)
    expect(lesson_form(page, a).locator('[name="has_lessons"]')).to_have_value('No')
