"""Regression coverage for primary navigation layout stability."""

import os
import re

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import Page, expect


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'


def login(page: Page, coachboard_url: str):
    page.goto(f'{coachboard_url}/login')
    identity = page.get_by_label('Username or email')
    if identity.count() == 0:
        page.goto(f'{coachboard_url}/logout')
        expect(page).to_have_url(re.compile(r'/login$'))
        identity = page.get_by_label('Username or email')
    identity.fill(TEST_USERNAME)
    page.locator('#password').fill(TEST_PASSWORD)
    page.get_by_role('button', name='Sign In').click()
    expect(page).to_have_url(re.compile(rf'^{re.escape(coachboard_url)}/?(?:#(?:overview|games))?$'))


def nav_snapshot(page: Page, selector: str):
    return page.locator(selector).evaluate(
        """nav => {
            const rect = nav.getBoundingClientRect();
            const links = [...nav.querySelectorAll('a')].filter(link => {
                const style = getComputedStyle(link);
                return style.display !== 'none' && style.visibility !== 'hidden';
            });
            return {
                top: rect.top,
                left: rect.left,
                width: rect.width,
                height: rect.height,
                labels: links.map(link => link.textContent.trim().replace(/\\s+/g, ' ')),
                links: links.map(link => {
                    const linkRect = link.getBoundingClientRect();
                    return {
                        left: linkRect.left,
                        top: linkRect.top,
                        width: linkRect.width,
                        height: linkRect.height,
                    };
                }),
            };
        }"""
    )


def mobile_shell_snapshot(page: Page):
    return page.evaluate(
        """() => {
            const header = document.querySelector('body > nav.navbar');
            const main = document.querySelector('body > main.container-fluid');
            const headerRect = header?.getBoundingClientRect();
            const mainRect = main?.getBoundingClientRect();
            return {
                scrollY: window.scrollY,
                header: headerRect ? {
                    top: headerRect.top,
                    left: headerRect.left,
                    width: headerRect.width,
                    height: headerRect.height,
                    position: getComputedStyle(header).position,
                } : null,
                main: mainRect ? {
                    top: mainRect.top,
                    left: mainRect.left,
                    width: mainRect.width,
                } : null,
            };
        }"""
    )


def assert_geometry_close(before, after, tolerance=2):
    for key in ('top', 'left', 'width', 'height'):
        assert abs(before[key] - after[key]) <= tolerance, (
            f'navigation {key} moved from {before[key]} to {after[key]}'
        )
    assert before['labels'] == after['labels']
    assert len(before['links']) == len(after['links'])
    for index, (first, second) in enumerate(zip(before['links'], after['links'])):
        for key in ('left', 'top', 'width', 'height'):
            assert abs(first[key] - second[key]) <= tolerance, (
                f'navigation link {index} {key} moved from {first[key]} to {second[key]}'
            )


def assert_mobile_shell_stable(before, after, tolerance=2):
    assert before['header'] and after['header']
    assert before['main'] and after['main']
    assert after['header']['position'] == 'fixed'
    assert abs(after['header']['top']) <= tolerance
    for section in ('header', 'main'):
        for key in ('top', 'left', 'width'):
            assert abs(before[section][key] - after[section][key]) <= tolerance, (
                f'mobile {section} {key} moved from {before[section][key]} to {after[section][key]}'
            )
    assert abs(before['header']['height'] - after['header']['height']) <= tolerance
    assert after['scrollY'] <= tolerance, f"primary workspace restored at scrollY={after['scrollY']}"


def settle_mobile_shell(page: Page):
    page.wait_for_timeout(120)
    for _ in range(10):
        if page.evaluate('window.scrollY') <= 2:
            return
        page.wait_for_timeout(50)


def test_mobile_primary_navigation_does_not_jump_between_workspaces(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    page.goto(coachboard_url, wait_until='domcontentloaded')
    settle_mobile_shell(page)

    nav = page.locator('#cb-global-mobile-nav')
    expect(nav).to_be_visible()
    expect(page.locator('nav.bottom-nav-fixed:visible')).to_have_count(1)
    expected_labels = ['Home', 'Game Day', 'Roster', 'Practice', 'More']
    expect(nav.locator('a')).to_have_count(5)
    assert [label.strip() for label in nav.locator('a').all_text_contents()] == expected_labels

    home_geometry = nav_snapshot(page, '#cb-global-mobile-nav')
    home_shell = mobile_shell_snapshot(page)
    assert home_shell['header']['position'] == 'fixed'
    assert abs(home_shell['header']['top']) <= 2

    # Reproduce the real phone behavior: a coach can be partway down Home and
    # then switch workspaces. The app shell should return to a stable top anchor
    # instead of letting Safari's restored/hash scroll move the header/content.
    page.evaluate('window.scrollTo(0, 320)')
    nav.get_by_text('Roster', exact=True).click()
    expect(page.locator('#roster')).to_have_class(re.compile(r'\bactive\b'))
    expect(nav.locator('[data-cb-mobile-section="roster"]')).to_have_class(re.compile(r'\bactive\b'))
    settle_mobile_shell(page)
    roster_geometry = nav_snapshot(page, '#cb-global-mobile-nav')
    roster_shell = mobile_shell_snapshot(page)
    assert_geometry_close(home_geometry, roster_geometry)
    assert_mobile_shell_stable(home_shell, roster_shell)

    nav.get_by_text('Practice', exact=True).click()
    expect(page.locator('#practice_plan')).to_have_class(re.compile(r'\bactive\b'))
    settle_mobile_shell(page)
    practice_geometry = nav_snapshot(page, '#cb-global-mobile-nav')
    practice_shell = mobile_shell_snapshot(page)
    assert_geometry_close(home_geometry, practice_geometry)
    assert_mobile_shell_stable(home_shell, practice_shell)

    with page.expect_navigation(wait_until='domcontentloaded'):
        nav.get_by_text('Game Day', exact=True).click()
    settle_mobile_shell(page)
    nav = page.locator('#cb-global-mobile-nav')
    expect(nav).to_be_visible()
    expect(nav.locator('[data-cb-mobile-section="game-day"]')).to_have_class(re.compile(r'\bactive\b'))
    game_day_geometry = nav_snapshot(page, '#cb-global-mobile-nav')
    game_day_shell = mobile_shell_snapshot(page)
    assert_geometry_close(home_geometry, game_day_geometry)
    assert_mobile_shell_stable(home_shell, game_day_shell)

    with page.expect_navigation(wait_until='domcontentloaded'):
        nav.get_by_text('Roster', exact=True).click()
    settle_mobile_shell(page)
    nav = page.locator('#cb-global-mobile-nav')
    expect(page.locator('#roster')).to_have_class(re.compile(r'\bactive\b'))
    expect(nav.locator('[data-cb-mobile-section="roster"]')).to_have_class(re.compile(r'\bactive\b'))
    return_geometry = nav_snapshot(page, '#cb-global-mobile-nav')
    return_shell = mobile_shell_snapshot(page)
    assert_geometry_close(home_geometry, return_geometry)
    assert_mobile_shell_stable(home_shell, return_shell)


def test_desktop_primary_navigation_keeps_geometry_and_active_state(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 1440, 'height': 900})
    login(page, coachboard_url)
    page.goto(coachboard_url, wait_until='domcontentloaded')

    nav = page.locator('.coach-primary-nav')
    expect(nav).to_be_visible()
    home_geometry = nav_snapshot(page, '.coach-primary-nav')

    nav.locator('[data-cb-section="roster"]').click()
    expect(page.locator('#roster')).to_have_class(re.compile(r'\bactive\b'))
    expect(nav.locator('[data-cb-section="roster"]')).to_have_class(re.compile(r'\bactive\b'))
    roster_geometry = nav_snapshot(page, '.coach-primary-nav')
    assert_geometry_close(home_geometry, roster_geometry)

    with page.expect_navigation(wait_until='domcontentloaded'):
        nav.locator('[data-cb-section="game-day"]').click()
    nav = page.locator('.coach-primary-nav')
    expect(nav).to_be_visible()
    expect(nav.locator('[data-cb-section="game-day"]')).to_have_class(re.compile(r'\bactive\b'))
    game_day_geometry = nav_snapshot(page, '.coach-primary-nav')
    assert_geometry_close(home_geometry, game_day_geometry)

    with page.expect_navigation(wait_until='domcontentloaded'):
        nav.locator('[data-cb-section="pitching"]').click()
    nav = page.locator('.coach-primary-nav')
    expect(nav).to_be_visible()
    expect(nav.locator('[data-cb-section="pitching"]')).to_have_class(re.compile(r'\bactive\b'))
    pitching_geometry = nav_snapshot(page, '.coach-primary-nav')
    assert_geometry_close(home_geometry, pitching_geometry)
