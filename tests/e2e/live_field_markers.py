"""Shared helpers for the live-field marker tests: a roster with realistic
long names, a live game using it, and a measurement of every marker."""

from datetime import date, timedelta
import re

from e2e_cleanup import delete_players_named, release_game


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'

#: position -> (name, jersey). A short (Luke), medium (Graham) and long
#: (Alexander Montgomery) name, the long one at shortstop where the marker
#: sits closest to the pitcher, and a long surname at centre field where the
#: marker sits nearest the top of the field.
LINEUP = {
    'P': ('Luke Ames', '4'),
    'C': ('Graham Ellis', '12'),
    '1B': ('Mateo Cruz', '27'),
    '2B': ('Owen Park', '3'),
    '3B': ('Jaxon Reyes', '15'),
    'SS': ('Alexander Montgomery', '22'),
    'LF': ('Eli Fox', '9'),
    'CF': ('Benjamin Hollingsworth', '31'),
    'RF': ('Carter Diaz', '7'),
}

ON_THE_FIELD = '#cbQuickDefense .cb-qd-field'
NEXT_INNING = '#live-board-prep-v3 .cb-next-field'

#: Every marker in a field: its button (the drag/tap target), its name box
#: and position text, and whether any marker covers another's text.
MEASURE = """(fieldSelector) => {
  const field = document.querySelector(fieldSelector);
  if (!field) return null;
  const f = field.getBoundingClientRect();
  const rect = r => ({left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height});
  const textRect = el => {
    const range = document.createRange(); range.selectNodeContents(el);
    const rs = [...range.getClientRects()].filter(r => r.width > 1);
    if (!rs.length) return null;
    return rect({left: Math.min(...rs.map(r => r.left)), top: Math.min(...rs.map(r => r.top)),
                 right: Math.max(...rs.map(r => r.right)), bottom: Math.max(...rs.map(r => r.bottom)),
                 width: 0, height: 0});
  };
  const lines = el => {
    const range = document.createRange(); range.selectNodeContents(el);
    return new Set([...range.getClientRects()].filter(r => r.width > 1).map(r => Math.round(r.top))).size;
  };
  const markers = [...field.querySelectorAll('.cb-qd-spot')].filter(el => el.getClientRects().length).map(spot => {
    const name = spot.querySelector('.cb-qd-name'), pos = spot.querySelector('.cb-qd-pos');
    const n = getComputedStyle(name), p = getComputedStyle(pos);
    return {
      position: spot.dataset.cbPosition || spot.dataset.nextPosition,
      label: name.innerText.trim().replace(/\\s+/g, ' '),
      posLabel: pos.innerText.trim().replace(/\\s+/g, ' '),
      accessibleName: spot.getAttribute('aria-label') || '',
      box: rect(spot.getBoundingClientRect()),
      nameBox: rect(name.getBoundingClientRect()),
      posText: textRect(pos),
      namePx: parseFloat(n.fontSize), nameLines: lines(name), posPx: parseFloat(p.fontSize),
      nameFits: name.scrollWidth <= name.clientWidth + 1 && name.scrollHeight <= name.clientHeight + 1,
      nameWraps: n.whiteSpace === 'normal' && n.textOverflow !== 'ellipsis',
    };
  });
  const hit = (a, b) => a && b && Math.min(a.right, b.right) - Math.max(a.left, b.left) > 1 && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 1;
  const overlaps = [];
  markers.forEach((a, i) => markers.forEach((b, j) => {
    if (i === j) return;
    if ((i < j && hit(a.nameBox, b.nameBox)) || hit(a.nameBox, b.posText)) overlaps.push([a.position, b.position]);
  }));
  const outside = markers.filter(m => m.box.left < f.left - 1 || m.box.right > f.right + 1 || m.box.top < f.top - 1 || m.box.bottom > f.bottom + 1).map(m => m.position);
  return {field: {width: f.width, height: f.height}, markers, overlaps, outside};
}"""


def login(page, base_url):
    page.goto(f'{base_url}/login')
    page.get_by_label('Username or email').fill(TEST_USERNAME)
    page.locator('#password').fill(TEST_PASSWORD)
    page.get_by_role('button', name='Sign In').click()
    page.wait_for_load_state('load')


def _alignment():
    return {pos: name for pos, (name, _) in LINEUP.items()}


def create_named_live_game(page, base_url, innings=None):
    """Add the named players, start a live game with them; return (game_id, player_ids).

    ``innings`` is the pregame plan; by default Innings 1 and 2 both use LINEUP.
    Anything created before a failure is removed again, so a failed setup
    leaves the shared roster as it found it.
    """
    game_id = None
    names = [name for name, _ in LINEUP.values()]
    try:
        for name, number in LINEUP.values():
            response = page.request.post(f'{base_url}/add_player', form={
                'name': name, 'number': number, 'position1': '', 'position2': '', 'position3': '',
                'throws': 'Right', 'bats': 'Right', 'notes': '', 'pitcher_role': 'Not a Pitcher',
                'roster_status': 'regular'}, headers={'X-Requested-With': 'XMLHttpRequest'}, max_redirects=0)
            # 409 live_roster_locked: a game is still live. A redirect: the name is already taken.
            added = response.status == 200 and 'json' in response.headers.get('content-type', '')
            assert added and response.json().get('status') == 'success', (
                f'could not add {name}: HTTP {response.status} '
                f'{response.headers.get("location", "")} {response.text()[:200]}')
        roster = page.request.get(f'{base_url}/api/roster').json()
        player_ids = [int(p['id']) for p in roster if p['name'] in set(names)]
        assert len(player_ids) == len(LINEUP), sorted(p['name'] for p in roster if p['name'] in set(names))

        response = page.request.post(f'{base_url}/game-day/add', form={
            'game_date': (date.today() + timedelta(days=13)).isoformat(), 'game_start_time': '15:00',
            'game_opponent': 'Marker Readability', 'game_location': 'Marker Field',
            'pitching_rule_set': 'USSSA'}, max_redirects=0)
        game_id = int(re.search(r'/game/(\d+)', response.headers['location']).group(1))
        for path, payload in (
            ('/add_lineup', {'title': 'Marker Lineup', 'lineup_player_ids': player_ids, 'associated_game_id': game_id}),
            ('/save_rotation', {'title': 'Marker Rotation',
                                'innings': innings or {'1': _alignment(), '2': _alignment()},
                                'associated_game_id': game_id}),
            (f'/api/live-game/{game_id}/start', {}),
        ):
            response = page.request.post(f'{base_url}{path}', data=payload)
            assert response.ok and response.json().get('status') == 'success', (path, response.text()[:200])
        return game_id, player_ids
    except BaseException:
        release_game(page.request, base_url, game_id)
        delete_players_named(page.request, base_url, names)
        raise


def remove_named_live_game(page, base_url, game_id, player_ids=None):
    """End and delete the game, then remove the named players."""
    release_game(page.request, base_url, game_id)
    # Leave the shared roster exactly as the other browser tests expect it.
    left = delete_players_named(page.request, base_url, [name for name, _ in LINEUP.values()])
    assert left == [], f'marker test players were not removed: {left}'


def open_view(page, base_url, game_id, view):
    page.goto(f'{base_url}/game/{game_id}')
    page.locator('#cbQuickDefense').wait_for(state='visible', timeout=20_000)
    if view == 'next':
        page.locator('#cb-now-next-switch [data-now-next="next"]').click()
        page.locator('#live-board-prep-v3 .cb-next-field').wait_for(state='visible', timeout=15_000)
    page.wait_for_timeout(700)
    return ON_THE_FIELD if view == 'now' else NEXT_INNING
