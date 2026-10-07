"""Driving Change Pitcher in browser tests: the current one-decision flow.

1. Change Pitcher (or tapping P) opens the pitcher list; the coach chooses
   the incoming pitcher. A flagged pitcher first shows its eligibility
   warning and the coach's decision (Continue / I verified / Use Anyway).
2. One question: where does the outgoing pitcher go? Each choice names the
   complete result -- "Bench Pat · SS open", "Pat → LF", or for an occupied
   spot "Pat → 1B · Frank → SS" (the displaced fielder takes the spot the
   new pitcher left) or "Pat → 1B · Frank → Bench" (the new pitcher came
   from the bench). The answer is saved as one pitching change.

`outcome_of` reads a choice the way a coach does, so a test can check that
what a button says is what gets saved.
"""

import re

from playwright.sync_api import Page, expect

from live_fixtures import filled, live_state, pitcher_changes, wait_for_field


PICKER = '#live-pitcher-picker-v2'
DESTINATION_QUESTION = '#live-pitcher-destination-v7'
TOAST = '#pitcher-change-toast-v6 .toast-body'
STALE = (
    'Defense changed on another device. '
    'Check the field and try the pitching change again.'
)


def open_change_pitcher(page: Page):
    page.locator('#liveChangePitcherBtn').click()
    picker = page.locator(PICKER)
    expect(picker).to_be_visible(timeout=10_000)
    return picker


def incoming_pitcher_row(picker, name: str):
    # Exact name: another suite's "Drag Bench Blake" contains "Bench Blake".
    return picker.locator('.pitcher-choice-v2', has=picker.page.get_by_text(name, exact=True))


def choose_incoming_pitcher(page: Page, name: str):
    """Change Pitcher → a Ready pitcher; returns the destination question."""
    picker = open_change_pitcher(page)
    incoming_pitcher_row(picker, name).click()
    expect(picker).not_to_be_visible(timeout=10_000)
    question = page.locator(DESTINATION_QUESTION)
    expect(question).to_be_visible(timeout=10_000)
    return question


def expect_destination_question(question, incoming: str, outgoing: str):
    expect(question.locator('[data-pc-title]')).to_have_text(f'{incoming} is going in to pitch')
    expect(question.locator('[data-pc-question]')).to_have_text(f'Where should {outgoing} go?')


def pitcher_outcome_choices(question):
    return [text.strip() for text in question.locator('[data-pc-choices] button').all_inner_texts()]


def choose_outgoing_destination(question, label: str):
    question.get_by_role('button', name=label, exact=True).click()
    expect(question).not_to_be_visible(timeout=10_000)


def record_pitching_changes(page: Page):
    posts = []
    page.on(
        'request',
        lambda request: posts.append(request.post_data_json)
        if request.method == 'POST' and 'complete-pitcher-change' in request.url
        else None,
    )
    return posts


def wait_for_pitcher_change(page: Page, url: str, game_id: int, expected):
    """Wait for the field `expected`; return the one pitching change that made it."""
    wait_for_field(page, url, game_id, expected)
    events = pitcher_changes(live_state(page, url, game_id))
    assert len(events) == 1, events
    assert filled(events[0]['after_alignment']) == expected
    return events[0]


def outcome_of(label: str, before, incoming: str, outgoing: str):
    """The field a destination choice describes, read as a coach reads it.

    Also checks the label is honest about the field it starts from: the
    spot it says is left open is the one the new pitcher left, and the
    player it says is displaced is the one there now.
    """
    before = filled(before)
    left = next((pos for pos, name in before.items() if pos != 'P' and name == incoming), None)
    after = {pos: name for pos, name in before.items() if pos != left}
    after['P'] = incoming

    bench = re.fullmatch(rf'Bench {re.escape(outgoing)}(?: · (\w+) open)?', label)
    if bench:
        assert bench.group(1) == left, (label, left)
        return after

    move = re.fullmatch(rf'{re.escape(outgoing)} → (\w+)(?: · (.+) → (\w+))?', label)
    assert move, f'not a destination choice: {label!r}'
    position, displaced, destination = move.groups()
    assert after.get(position) == displaced, (label, after.get(position))
    after[position] = outgoing
    if displaced and destination != 'Bench':
        assert not after.get(destination), (label, destination)
        after[destination] = displaced
    return after
