"""Guardrail: who polls /api/game-day/<id>/readiness, and who listens.

READINESS OWNERSHIP AFTER THIS SLICE
------------------------------------
``static/js/game_prep_readiness.js`` is the periodic readiness owner for the
Start Game UI. It polls every 5s for its own pregame panel and publishes each
successful response as ``coachboard:readiness``.
``static/js/game_setup_ux.js`` subscribes to that event and no longer runs a
readiness timer of its own; the 8s poller it used to own was a third duplicate
request for the same payload.

The consequence is a real coupling, and it is the reason these tests exist:
**stopping or gating the owner's poll also stops periodic Start Game readiness
updates.** The polling audit identified suppressing the owner's fetch while
``is_live`` is true as a further optimisation -- render() already discards live
payloads, so it looks free. After this slice it is not free: it would leave
game_setup_ux.js with no periodic source at all. Give the Start Game UI another
periodic owner before making that change.

What still protects the Start Game button if the publish never arrives:
game_setup_ux.js keeps one direct fetch on init and one on ``visibilitychange``.
Both are asserted below so a future cleanup cannot quietly remove the last
fallback and leave the button permanently stale.
"""

from guardrail_readiness_support import (
    body_without_listener_callbacks,
    dispatched_events,
    functions,
    interval_sites,
    listened_events,
    listener_callbacks,
    module_source,
    readiness_fetchers,
    readiness_intervals,
    readiness_intervals_in_source,
)


OWNER = 'game_prep_readiness.js'
SUBSCRIBER = 'game_setup_ux.js'
EVENT = 'coachboard:readiness'

# Every periodic readiness poller CoachBoard is allowed to ship, and its
# interval. Enforced in both directions: a new poller fails, and a poller that
# disappears fails too, because the entries here are load-bearing -- the owner's
# 5s tick is the Start Game UI's only periodic update.
EXPECTED_READINESS_POLLERS = {
    OWNER: 5000,
    'pregame_quick_start.js': 10000,
}


def test_readiness_pollers_match_the_declared_set_exactly():
    found = {
        module: [site['delay_ms'] for site in sites]
        for module, sites in readiness_intervals().items()
    }
    expected = {module: [delay] for module, delay in EXPECTED_READINESS_POLLERS.items()}
    assert found == expected, (
        'The set of periodic readiness pollers changed. A new one duplicates an '
        'existing request; a removed one may have been the last periodic source '
        'for a consumer that no longer fetches for itself. Update '
        'EXPECTED_READINESS_POLLERS deliberately, not to make this pass.'
    )


def test_game_setup_ux_has_no_readiness_interval_but_keeps_the_pitching_one():
    source = module_source(SUBSCRIBER)

    assert readiness_intervals_in_source(source) == [], (
        f'{SUBSCRIBER} must not poll readiness on a timer; it subscribes to '
        f'{EVENT} instead.'
    )

    delays = sorted(
        site['delay_ms'] for site in interval_sites(source)
        if site['delay_ms'] is not None
    )
    assert delays == [12000], (
        'The 12s pitching interval is unrelated to readiness and must survive '
        f'this slice. Found intervals: {delays}'
    )


def test_game_setup_ux_still_fetches_readiness_directly_on_init():
    """The init fetch specifically, not just any refreshReadiness() anywhere.

    A substring test over the whole module -- or even over start()'s whole
    body -- passes on the visibilitychange handler's call alone, so it cannot
    tell the two fallback paths apart. Strip the nested listener callbacks and
    assert the direct call survives.
    """
    source = module_source(SUBSCRIBER)
    assert 'refreshReadiness' in readiness_fetchers(source)

    start = functions(source).get('start')
    assert start, f'{SUBSCRIBER} no longer defines start().'

    direct = body_without_listener_callbacks(start)
    assert 'refreshReadiness();' in direct, (
        'start() must call refreshReadiness() directly. This is the first of '
        'two fallbacks that let the Start Game button converge without the '
        'owner module; the visibilitychange call is the second and is asserted '
        'separately.'
    )


def test_game_setup_ux_still_refreshes_readiness_when_the_tab_becomes_visible():
    callbacks = listener_callbacks(module_source(SUBSCRIBER), 'visibilitychange')
    assert callbacks, f'{SUBSCRIBER} lost its visibilitychange handler.'
    assert any('refreshReadiness()' in callback for callback in callbacks), (
        'Resume must still perform a direct readiness fetch: it is the second '
        'of the two fallbacks and the only one available after the first load.'
    )


def test_the_owner_publishes_the_readiness_event():
    assert EVENT in dispatched_events(module_source(OWNER))


def test_game_setup_ux_subscribes_to_the_readiness_event():
    source = module_source(SUBSCRIBER)
    assert EVENT in listened_events(source)

    callbacks = listener_callbacks(source, EVENT)
    assert len(callbacks) == 1
    callback = callbacks[0]

    assert 'game_id' in callback, 'The subscriber must reject a mismatched game.'
    assert 'applyStartReadiness' in callback, (
        'The subscriber must feed the published payload into the existing '
        'renderer rather than reimplementing it.'
    )
    assert 'fetch(' not in callback, (
        'Consuming the event must not issue another readiness request -- that '
        'would defeat the whole slice.'
    )


def test_the_owner_keeps_its_interval_and_media_query_refresh():
    source = module_source(OWNER)

    delays = [site['delay_ms'] for site in readiness_intervals_in_source(source)]
    assert delays == [5000], 'The owner interval is not this slice to change.'

    assert 'mobileMedia.addEventListener?.(' in source, (
        'The media-query refresh is existing behaviour and must survive.'
    )


def test_the_ownership_dependency_is_documented_in_both_modules():
    owner = module_source(OWNER)
    subscriber = module_source(SUBSCRIBER)

    assert SUBSCRIBER in owner, (
        'The owner must name its dependant, so anyone gating this poller sees '
        'that the Start Game UI depends on it.'
    )
    assert 'is_live' in owner, (
        'The owner must specifically warn against the is_live gating '
        'optimisation the audit identified.'
    )
    assert OWNER in subscriber, (
        'The subscriber must name where its periodic updates now come from.'
    )


# --- scanner self-tests -----------------------------------------------------
#
# Without these, a scanner that stopped matching would report zero pollers and
# every assertion above would pass vacuously.

READINESS_URL = '`/api/game-day/${gameId}/readiness`'


def test_a_bare_identifier_interval_delegating_to_a_fetch_is_counted():
    source = f'''
      async function refresh() {{
        const response = await fetch({READINESS_URL});
      }}
      window.setInterval(refresh, 5000);
    '''
    assert [site['delay_ms'] for site in readiness_intervals_in_source(source)] == [5000]


def test_an_arrow_interval_delegating_through_a_helper_is_counted():
    source = f'''
      async function load() {{
        await fetch({READINESS_URL});
      }}
      function maybe() {{ if (!document.hidden) load(); }}
      window.setInterval(() => {{ maybe(); }}, 10000);
    '''
    assert [site['delay_ms'] for site in readiness_intervals_in_source(source)] == [10000]


def test_an_interval_that_never_reaches_readiness_is_not_counted():
    source = f'''
      async function refresh() {{
        await fetch({READINESS_URL});
      }}
      async function pitching() {{
        await fetch(`/api/game-day/${{gameId}}/pitching-rules`);
      }}
      window.setInterval(pitching, 12000);
    '''
    assert readiness_intervals_in_source(source) == []


def test_a_comment_naming_the_readiness_url_does_not_create_a_poller():
    """Regression: prose must not be able to steer this guardrail.

    The first version of this scanner was not comment-aware, and the ownership
    comment this slice added to game_setup_ux.js made start() register as a
    readiness fetcher.
    """
    source = '''
      function start() {
        // Periodic readiness now arrives from another module, which polls
        // /api/game-day/<id>/readiness every 5s and publishes the response.
        window.setInterval(other, 12000);
      }
      function other() { return 1; }
    '''
    assert readiness_fetchers(source) == set()
    assert readiness_intervals_in_source(source) == []


def test_a_readiness_fetch_with_no_interval_is_not_a_poller():
    source = f'''
      async function refreshReadiness() {{
        await fetch({READINESS_URL});
      }}
      document.addEventListener('visibilitychange', () => refreshReadiness());
    '''
    assert readiness_fetchers(source) == {'refreshReadiness'}
    assert readiness_intervals_in_source(source) == []


def test_a_call_only_inside_a_listener_is_not_counted_as_a_direct_call():
    """Regression: this is exactly the weakness the init-fetch test had.

    Without stripping, the body below reads as though start() fetches on init,
    when the only call lives in the visibilitychange handler.
    """
    body = """{
      ensureStartFeedback();
      document.addEventListener('visibilitychange', () => {
        if (!document.hidden) {
          refreshReadiness();
        }
      });
    }"""
    assert 'refreshReadiness();' in body
    assert 'refreshReadiness();' not in body_without_listener_callbacks(body)


def test_a_direct_call_survives_stripping_alongside_a_listener():
    body = """{
      refreshReadiness();
      document.addEventListener('visibilitychange', () => {
        refreshReadiness();
      });
    }"""
    assert 'refreshReadiness();' in body_without_listener_callbacks(body)
