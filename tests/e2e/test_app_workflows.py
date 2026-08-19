"""Create, update, persist, and delete coverage for CoachBoard feature areas."""

import os
import re
from datetime import date, timedelta

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import Page, expect


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'


def login(page: Page, coachboard_url: str, username=TEST_USERNAME, password=TEST_PASSWORD):
    page.goto(f'{coachboard_url}/login')
    identity = page.get_by_label('Username or email')
    if identity.count() == 0:
        page.goto(f'{coachboard_url}/logout')
        expect(page).to_have_url(re.compile(r'/login$'))
        identity = page.get_by_label('Username or email')
    identity.fill(username)
    page.locator('#password').fill(password)
    page.get_by_role('button', name='Sign In').click()
    expect(page).to_have_url(re.compile(rf'^{re.escape(coachboard_url)}/?(?:#games)?$'))


def get_json(page: Page, coachboard_url: str, path: str):
    response = page.request.get(f'{coachboard_url}{path}')
    assert response.status == 200, f'GET {path} returned {response.status}: {response.text()}'
    return response.json()


def post_json(page: Page, coachboard_url: str, path: str, data, expected_status=200):
    response = page.request.post(f'{coachboard_url}{path}', data=data)
    assert response.status == expected_status, f'POST {path} returned {response.status}: {response.text()}'
    payload = response.json()
    if expected_status < 400:
        assert payload.get('status') == 'success', f'POST {path} failed: {payload}'
    return payload


def delete_json(page: Page, coachboard_url: str, path: str, expected_status=200):
    response = page.request.fetch(f'{coachboard_url}{path}', method='DELETE')
    assert response.status == expected_status, f'DELETE {path} returned {response.status}: {response.text()}'
    payload = response.json()
    if expected_status < 400:
        assert payload.get('status') == 'success', f'DELETE {path} failed: {payload}'
    return payload


def post_form(page: Page, coachboard_url: str, path: str, form):
    response = page.request.post(
        f'{coachboard_url}{path}',
        form=form,
        max_redirects=0,
    )
    assert response.status in {302, 303}, f'POST {path} returned {response.status}: {response.text()}'
    return response


def get_redirect(page: Page, coachboard_url: str, path: str):
    response = page.request.get(f'{coachboard_url}{path}', max_redirects=0)
    assert response.status in {302, 303}, f'GET {path} returned {response.status}: {response.text()}'
    return response


def item_named(items, name, key='name'):
    return next((item for item in items if item.get(key) == name), None)


def complete_alignment(pitcher='Pitcher Pat'):
    return {
        'P': pitcher,
        'C': 'Catcher Cole',
        '1B': 'First Frank',
        '2B': 'Second Sam',
        '3B': 'Third Theo',
        'SS': 'Shortstop Shawn',
        'LF': 'Left Lee',
        'CF': 'Center Casey',
        'RF': 'Right Riley',
    }


def test_roster_profiles_order_and_lineup_crud(page: Page, coachboard_url: str):
    login(page, coachboard_url)

    post_form(page, coachboard_url, '/add_player', {
        'name': 'Automation Alex',
        'number': '44',
        'position1': 'OF',
        'position2': '2B',
        'throws': 'Right',
        'bats': 'Left',
        'pitcher_role': 'Reliever',
        'notes': 'Created by Playwright',
    })
    roster = get_json(page, coachboard_url, '/api/roster')
    player = item_named(roster, 'Automation Alex')
    assert player is not None

    update = page.request.post(f'{coachboard_url}/update_player_inline/{player["id"]}', form={
        'name': 'Automation Alex',
        'number': '45',
        'position1': 'CF',
        'position2': '2B',
        'position3': '',
        'throws': 'Right',
        'bats': 'Left',
        'pitcher_role': 'Reliever',
        'notes': 'Updated by Playwright',
    })
    assert update.status == 200 and update.json()['status'] == 'success'

    post_json(page, coachboard_url, f'/update_pitching_profile/{player["id"]}', {
        'traits': ['Change of Pace', 'Composed Under Pressure'],
    })
    profiles = get_json(page, coachboard_url, '/api/roster-pitching-profiles')
    assert profiles['profiles'][str(player['id'])] == ['Change of Pace', 'Composed Under Pressure']

    order = [player['id']] + [row['id'] for row in roster if row['id'] != player['id']]
    post_json(page, coachboard_url, '/save_player_order', {'player_order': order})
    session_data = get_json(page, coachboard_url, '/api/session_data')
    assert session_data['player_order'][0] == player['id']

    lineup = post_json(page, coachboard_url, '/add_lineup', {
        'title': 'Automation Lineup',
        'lineup_data': ['Pitcher Pat', 'Catcher Cole', 'First Frank'],
        'lineup_player_ids': [1, 2, 3],
        'is_default': True,
    })
    lineup_id = lineup['new_id']
    assert lineup['lineup']['is_default'] is True
    assert lineup['lineup']['lineup_player_ids'] == [1, 2, 3]
    assert [entry['batting_order'] for entry in lineup['lineup']['lineup_entries']] == [1, 2, 3]
    edited = post_json(page, coachboard_url, f'/edit_lineup/{lineup_id}', {
        'title': 'Automation Lineup Updated',
        'lineup_data': ['Catcher Cole', 'Pitcher Pat', 'First Frank'],
        'lineup_player_ids': [2, 1, 3],
        'is_default': True,
    })
    assert edited['lineup']['lineup_positions'][0] == 'Catcher Cole'
    invalid = post_json(page, coachboard_url, '/add_lineup', {
        'title': 'Invalid Cross-Team Lineup',
        'lineup_player_ids': [100],
    }, expected_status=400)
    assert 'not on this team' in invalid['message']
    get_redirect(page, coachboard_url, f'/delete_lineup/{lineup_id}')
    assert item_named(get_json(page, coachboard_url, '/api/lineups'), 'Automation Lineup Updated', 'title') is None

    identity_lineup = post_json(page, coachboard_url, '/add_lineup', {
        'title': 'Stable Player Identity',
        'lineup_player_ids': [player['id']],
    })
    renamed = page.request.post(f'{coachboard_url}/update_player_inline/{player["id"]}', form={
        'name': 'Automation Alexis',
        'number': '45',
        'position1': 'CF',
        'position2': '2B',
        'position3': '',
        'throws': 'Right',
        'bats': 'Left',
        'pitcher_role': 'Reliever',
        'notes': 'Renamed after saving a lineup',
    })
    assert renamed.status == 200
    saved_identity = item_named(get_json(page, coachboard_url, '/api/lineups'), 'Stable Player Identity', 'title')
    assert saved_identity['lineup_player_ids'] == [player['id']]
    assert saved_identity['lineup_positions'] == ['Automation Alexis']
    get_redirect(page, coachboard_url, f'/delete_lineup/{identity_lineup["new_id"]}')

    get_redirect(page, coachboard_url, f'/delete_player/{player["id"]}')
    assert item_named(get_json(page, coachboard_url, '/api/roster'), 'Automation Alex') is None
    assert item_named(get_json(page, coachboard_url, '/api/roster'), 'Automation Alexis') is None


def test_rotation_and_starting_defense_template_crud(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    alignment = complete_alignment()

    rotation = post_json(page, coachboard_url, '/api/rotation-template/save', {
        'title': 'Automation Full Rotation',
        'innings': {'1': alignment, '2': alignment},
    })
    rotation_id = rotation['id']
    assert len(rotation['rotation']['innings']) == rotation['regulation_innings']

    updated_alignment = dict(alignment)
    updated_alignment['LF'], updated_alignment['RF'] = updated_alignment['RF'], updated_alignment['LF']
    updated = post_json(page, coachboard_url, '/api/rotation-template/save', {
        'id': rotation_id,
        'title': 'Automation Full Rotation Updated',
        'innings': {'1': updated_alignment},
    })
    assert updated['rotation']['innings']['1']['LF'] == 'Right Riley'

    starting = dict(alignment)
    starting.pop('P')
    defense = post_json(page, coachboard_url, '/api/starting-defense-template/save', {
        'title': 'Automation Starting Defense',
        'innings': {'1': starting},
    })
    defense_id = defense['id']
    assert 'P' not in defense['rotation']['innings']['1']

    page.goto(f'{coachboard_url}/rotation-template/{rotation_id}')
    expect(page.locator('#rteTemplateName')).to_have_value('Automation Full Rotation Updated')
    page.goto(f'{coachboard_url}/starting-defense-template/{defense_id}')
    expect(page.locator('#rteTemplateName')).to_have_value('Automation Starting Defense')

    get_redirect(page, coachboard_url, f'/delete_rotation/{rotation_id}')
    get_redirect(page, coachboard_url, f'/delete_rotation/{defense_id}')
    titles = {row['title'] for row in get_json(page, coachboard_url, '/api/rotations')}
    assert 'Automation Full Rotation Updated' not in titles
    assert not any('Automation Starting Defense' in title for title in titles)


def test_scouting_lists_move_and_roster_promotion(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    post_json(page, coachboard_url, '/add_scouted_player', {
        'scouted_player_name': 'Automation Scout',
        'scouted_player_type': 'targets',
        'scouted_player_pos1': 'SS',
        'scouted_player_pos2': '2B',
        'scouted_player_throws': 'Right',
        'scouted_player_bats': 'Left',
    })
    scouting = get_json(page, coachboard_url, '/api/scouting_list')
    scout = item_named(scouting['targets'], 'Automation Scout')
    assert scout is not None

    post_form(page, coachboard_url, f'/move_scouted_player/targets/committed/{scout["id"]}', {})
    moved = item_named(get_json(page, coachboard_url, '/api/scouting_list')['committed'], 'Automation Scout')
    assert moved is not None

    post_form(page, coachboard_url, f'/move_scouted_player_to_roster/{moved["id"]}', {})
    roster_player = item_named(get_json(page, coachboard_url, '/api/roster'), 'Automation Scout')
    assert roster_player is not None
    get_redirect(page, coachboard_url, f'/delete_player/{roster_player["id"]}')

    post_json(page, coachboard_url, '/add_scouted_player', {
        'scouted_player_name': 'Automation Remove Scout',
        'scouted_player_type': 'not_interested',
    })
    removable = item_named(
        get_json(page, coachboard_url, '/api/scouting_list')['not_interested'],
        'Automation Remove Scout',
    )
    get_redirect(page, coachboard_url, f'/delete_scouted_player/not_interested/{removable["id"]}')
    assert item_named(
        get_json(page, coachboard_url, '/api/scouting_list')['not_interested'],
        'Automation Remove Scout',
    ) is None


def test_development_notes_lessons_and_coach_notes_crud(page: Page, coachboard_url: str):
    login(page, coachboard_url)

    post_form(page, coachboard_url, '/add_focus/Center Casey', {
        'skill': 'fielding',
        'focus_text': 'Automation route communication',
        'notes': 'Created by Playwright',
    })
    development = get_json(page, coachboard_url, '/api/player_development')
    focus = next(item for item in development['Center Casey'] if item['focus'] == 'Automation route communication')
    post_form(page, coachboard_url, f'/update_focus/{focus["id"]}', {
        'focus_text': 'Automation route communication updated',
        'notes': 'Updated note',
        'progress_notes': 'Improving',
    })
    get_redirect(page, coachboard_url, f'/complete_focus/{focus["id"]}')
    completed = next(item for item in get_json(page, coachboard_url, '/api/player_development')['Center Casey'] if item['id'] == focus['id'])
    assert completed['status'] == 'completed'

    post_form(page, coachboard_url, '/update_lesson_info/8', {
        'has_lessons': 'Yes',
        'lesson_focus': 'Automation hitting lesson',
    })
    center = next(row for row in get_json(page, coachboard_url, '/api/roster') if row['id'] == 8)
    assert center['lesson_focus'] == 'Automation hitting lesson'
    get_redirect(page, coachboard_url, '/delete_lesson_info/8')

    post_form(page, coachboard_url, '/add_note/team_notes', {
        'note_text': 'Automation team note',
    })
    post_form(page, coachboard_url, '/add_note/player_notes', {
        'player_name': 'Center Casey',
        'note_text': 'Automation player note',
    })
    notes = get_json(page, coachboard_url, '/api/collaboration_notes')
    team_note = next(row for row in notes['team_notes'] if row['text'] == 'Automation team note')
    player_note = next(row for row in notes['player_notes'] if row['text'] == 'Automation player note')
    post_form(page, coachboard_url, '/edit_note', {
        'note_id': str(team_note['id']),
        'note_type': 'team_notes',
        'note_text': 'Automation team note updated',
    })
    get_redirect(page, coachboard_url, f'/delete_note/team_notes/{team_note["id"]}')
    get_redirect(page, coachboard_url, f'/delete_note/player_notes/{player_note["id"]}')
    get_redirect(page, coachboard_url, f'/delete_focus/{focus["id"]}')


def test_practice_plan_attendance_tasks_clone_and_signs_crud(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    plan_date = (date.today() + timedelta(days=20)).isoformat()
    clone_date = (date.today() + timedelta(days=21)).isoformat()

    post_form(page, coachboard_url, '/add_practice_plan', {
        'plan_date': plan_date,
        'general_notes': 'Automation practice plan',
        'emphasis': 'Automation communication',
        'warm_up': 'Dynamic warm-up',
        'infield_outfield': 'Cutoffs',
        'hitting': 'Situational hitting',
        'pitching_catching': 'Bullpens',
    })
    plans = get_json(page, coachboard_url, '/api/practice_plans')
    plan = next(row for row in plans if row['general_notes'] == 'Automation practice plan')

    post_form(page, coachboard_url, f'/add_task_to_plan/{plan["id"]}', {
        'task_text': 'Automation practice task',
    })
    plan = next(row for row in get_json(page, coachboard_url, '/api/practice_plans') if row['id'] == plan['id'])
    task = next(row for row in plan['tasks'] if row['text'] == 'Automation practice task')
    post_json(page, coachboard_url, f'/update_task_status/{plan["id"]}/{task["id"]}', {'status': 'complete'})
    post_form(page, coachboard_url, f'/update_practice_attendance/{plan["id"]}', {
        'absent_players': '2',
    })
    plan = next(row for row in get_json(page, coachboard_url, '/api/practice_plans') if row['id'] == plan['id'])
    assert plan['absent_player_ids'] == [2]

    clone = post_json(page, coachboard_url, f'/clone_practice_plan/{plan["id"]}', {
        'plan_date': clone_date,
        'copy_tasks': True,
    })
    clone_id = clone['new_plan_id']
    cloned = next(row for row in get_json(page, coachboard_url, '/api/practice_plans') if row['id'] == clone_id)
    assert cloned['general_notes'] == 'Automation practice plan'
    assert cloned['absent_player_ids'] == []
    assert all(row['status'] == 'pending' for row in cloned['tasks'])

    post_form(page, coachboard_url, f'/edit_practice_plan/{clone_id}', {
        'plan_date': clone_date,
        'general_notes': 'Automation cloned practice updated',
    })
    get_redirect(page, coachboard_url, f'/delete_task/{plan["id"]}/{task["id"]}')
    get_redirect(page, coachboard_url, f'/delete_practice_plan/{clone_id}')
    get_redirect(page, coachboard_url, f'/delete_practice_plan/{plan["id"]}')

    post_form(page, coachboard_url, '/add_sign', {
        'sign_name': 'Automation Bunt',
        'sign_indicator': 'Touch cap',
    })
    sign = item_named(get_json(page, coachboard_url, '/api/signs'), 'Automation Bunt')
    post_form(page, coachboard_url, f'/update_sign/{sign["id"]}', {
        'sign_name': 'Automation Bunt Updated',
        'sign_indicator': 'Touch sleeve',
    })
    updated_sign = item_named(get_json(page, coachboard_url, '/api/signs'), 'Automation Bunt Updated')
    assert updated_sign['indicator'] == 'Touch sleeve'
    get_redirect(page, coachboard_url, f'/delete_sign/{sign["id"]}')


def test_pitching_outing_targets_rules_and_validation(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    outing_date = date.today().isoformat()

    post_form(page, coachboard_url, '/add_pitching', {
        'pitch_date': outing_date,
        'player_id': '8',
        'opponent': 'Automation Aces',
        'pitches': '27',
        'innings': '1.2',
        'outing_type': 'Game',
        'pitcher_type': 'Reliever',
    })
    pitching = get_json(page, coachboard_url, '/api/pitching_data')['pitching']
    outing = next(row for row in pitching if row['opponent'] == 'Automation Aces')
    assert outing['pitches'] == 27

    post_form(page, coachboard_url, f'/edit_pitching/{outing["id"]}', {
        'pitch_date': outing_date,
        'player_id': '8',
        'opponent': 'Automation Aces Updated',
        'pitches': '31',
        'innings': '2.0',
        'outing_type': 'Game',
        'pitcher_type': 'Starter',
    })
    edited = next(row for row in get_json(page, coachboard_url, '/api/pitching_data')['pitching'] if row['id'] == outing['id'])
    assert edited['pitches'] == 31 and edited['opponent'] == 'Automation Aces Updated'

    post_json(page, coachboard_url, '/save_player_target', {
        'player_id': 8,
        'local_date': outing_date,
        'target_pitches': 40,
        'reason': 'Automation target',
    })
    summary = get_json(page, coachboard_url, '/api/pitching_data')['pitch_count_summary']
    assert 'Center Casey' in summary
    post_json(page, coachboard_url, '/save_player_target', {
        'player_id': 8,
        'local_date': outing_date,
        'target_pitches': '',
    })

    invalid = page.request.post(f'{coachboard_url}/add_pitching', form={
        'pitch_date': outing_date,
        'player_id': '8',
        'opponent': 'Invalid Innings',
        'pitches': '20',
        'innings': '1.3',
        'outing_type': 'Game',
    })
    assert invalid.status == 200
    assert 'whole innings plus 0, 1, or 2 outs' in invalid.text()

    get_redirect(page, coachboard_url, f'/delete_pitching/{outing["id"]}')
    assert not any(row['id'] == outing['id'] for row in get_json(page, coachboard_url, '/api/pitching_data')['pitching'])


def test_admin_settings_users_teams_registration_and_passwords(page: Page, coachboard_url: str):
    login(page, coachboard_url)

    page.goto(f'{coachboard_url}/admin/settings')
    original_code = page.locator('#teamRegistrationCode').input_value()
    post_form(page, coachboard_url, '/admin/settings/update', {
        'team_name': 'Playwright Prospects Updated',
        'outfielder_count': '4',
        'age_group': '12U',
        'pitching_rule_set': 'MLB Pitch Smart',
        'primary_color': '#102A66',
        'secondary_color': '#E5E7EB',
        'timezone': 'America/Indiana/Indianapolis',
        'batting_order_mode': 'fixed',
        'fixed_lineup_size': '8',
    })
    page.goto(coachboard_url)
    expect(page.locator('.navbar-brand-text')).to_contain_text('Playwright Prospects Updated')
    post_form(page, coachboard_url, '/admin/settings/regulation-innings', {'regulation_innings': '7'})
    settings = get_json(page, coachboard_url, '/api/team-game-settings')
    assert settings['regulation_innings'] == 7
    assert settings['batting_order_mode'] == 'fixed'
    assert settings['fixed_lineup_size'] == 8
    fixed_lineup = post_json(page, coachboard_url, '/add_lineup', {
        'title': 'Eight Batter Game Lineup',
        'lineup_player_ids': list(range(1, 9)),
        'associated_game_id': 1,
    })
    readiness = get_json(page, coachboard_url, '/api/game-day/1/readiness')['readiness']
    assert readiness['lineup_mode'] == 'fixed'
    assert readiness['lineup_expected_count'] == 8
    assert readiness['lineup_ready'] is True
    get_redirect(page, coachboard_url, f'/delete_lineup/{fixed_lineup["new_id"]}')
    post_form(page, coachboard_url, '/admin/settings/regulation-innings', {'regulation_innings': ''})

    # Restore shared team settings before testing the other admin panels so a
    # later assertion cannot leak temporary values into another browser test.
    post_form(page, coachboard_url, '/admin/settings/update', {
        'team_name': 'Playwright Prospects',
        'outfielder_count': '3',
        'age_group': '12U',
        'pitching_rule_set': 'MLB Pitch Smart',
        'primary_color': '#102A66',
        'secondary_color': '#E5E7EB',
        'timezone': 'America/Indiana/Indianapolis',
        'batting_order_mode': 'bat_all',
        'fixed_lineup_size': '9',
    })

    post_form(page, coachboard_url, '/admin/add_user', {
        'username': 'automation-user',
        'password': 'AutomationPass123!',
        'full_name': 'Automation User',
        'role': 'Assistant Coach',
        'team_id': '1',
    })
    post_form(page, coachboard_url, '/admin/edit_user/automation-user', {
        'full_name': 'Automation User Updated',
        'role': 'Game Changer',
    })
    password_help = page.request.post(f'{coachboard_url}/admin/reset_password/automation-user', form={})
    assert password_help.status == 200
    assert 'Automation User Updated' in password_help.text()
    page.goto(f'{coachboard_url}/admin/users')
    expect(page.get_by_text('Automation User Updated').first).to_be_visible()

    post_form(page, coachboard_url, '/admin/create_team', {'team_name': 'Automation Temporary Team'})
    page.goto(f'{coachboard_url}/admin/teams')
    team_item = page.locator('li.list-group-item').filter(has_text='Automation Temporary Team')
    expect(team_item).to_be_visible()
    modal_target = team_item.locator('button[data-bs-target^="#deleteTeamModal-"]').get_attribute('data-bs-target')
    assert modal_target and modal_target.rsplit('-', 1)[-1].isdigit()
    get_redirect(page, coachboard_url, f'/admin/delete_team/{modal_target.rsplit("-", 1)[-1]}')

    page.context.clear_cookies()
    response = page.request.post(f'{coachboard_url}/register', form={
        'username': 'automation-register',
        'email': 'automation-register@example.test',
        'full_name': 'Automation Registered Coach',
        'password': 'AutomationRegister123!',
        'registration_code': original_code,
    })
    assert response.status == 200
    assert 'Playwright Prospects' in response.text()

    page.context.clear_cookies()
    login(page, coachboard_url, 'automation-register', 'AutomationRegister123!')
    page.goto(f'{coachboard_url}/change_password')
    page.locator('#current_password').fill('AutomationRegister123!')
    page.locator('#new_password').fill('AutomationChanged123!')
    page.locator('#confirm_new_password').fill('AutomationChanged123!')
    page.get_by_role('button', name='Update Password').click()
    expect(page).to_have_url(re.compile(r'/$'))
    page.context.clear_cookies()
    login(page, coachboard_url, 'automation-register', 'AutomationChanged123!')

    page.context.clear_cookies()
    login(page, coachboard_url)
    post_form(page, coachboard_url, '/admin/delete_user/automation-user', {})
    post_form(page, coachboard_url, '/admin/delete_user/automation-register', {})

    page.goto(f'{coachboard_url}/admin/settings')
    code_before_rotation = page.locator('#teamRegistrationCode').input_value()
    post_form(page, coachboard_url, '/admin/settings/rotate-registration-code', {})
    page.goto(f'{coachboard_url}/admin/settings')
    assert page.locator('#teamRegistrationCode').input_value() != code_before_rotation

    recovery = page.request.post(f'{coachboard_url}/forgot_password', form={
        'identity': 'unknown-automation@example.test',
    })
    assert recovery.status == 200
    assert 'Internal Server Error' not in recovery.text()
