"""Regression coverage for shared mobile bottom-nav clearance."""

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


def css_px(page: Page, selector: str, property_name: str) -> float:
    return page.locator(selector).evaluate(
        """(node, propertyName) => parseFloat(getComputedStyle(node)[propertyName]) || 0""",
        property_name,
    )


def test_mobile_bottom_nav_has_one_clearance_owner(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    page.goto(f'{coachboard_url}/#overview', wait_until='domcontentloaded')

    nav = page.locator('#cb-global-mobile-nav')
    expect(nav).to_be_visible()
    expect(page.locator('#overview')).to_have_class(re.compile(r'\bactive\b'))

    geometry = nav.evaluate(
        """nav => {
            const rect = nav.getBoundingClientRect();
            const main = document.querySelector('main.container-fluid');
            return {
                navBottom: rect.bottom,
                navHeight: rect.height,
                viewportHeight: window.innerHeight,
                mainPaddingBottom: parseFloat(getComputedStyle(main).paddingBottom) || 0,
                rootBackground: getComputedStyle(document.documentElement).backgroundColor,
            };
        }"""
    )

    # The app bar itself must meet the web viewport edge. Any space below this
    # in iPhone Chrome belongs to browser chrome, not a second CoachBoard spacer.
    assert abs(geometry['viewportHeight'] - geometry['navBottom']) <= 1
    assert geometry['rootBackground'] == 'rgb(255, 255, 255)'
    assert geometry['mainPaddingBottom'] >= geometry['navHeight']
    assert geometry['mainPaddingBottom'] - geometry['navHeight'] <= 12

    # Home used to add another 84px beneath the shared main clearance.
    assert css_px(page, '#overview', 'paddingBottom') == 0

    nav.get_by_text('More', exact=True).click()
    expect(page.locator('#more')).to_have_class(re.compile(r'\bactive\b'))
    expect(page.locator('#more .cb-mobile-more-shell')).to_be_visible()
    assert css_px(page, '#more .cb-mobile-more-shell', 'paddingBottom') <= 8

    page.locator('#more a[href="#collaboration"]').click()
    expect(page.locator('#collaboration')).to_have_class(re.compile(r'\bactive\b'))
    # Coach Notes used to add its own 96px mobile buffer too.
    assert css_px(page, '#collaboration', 'paddingBottom') == 0


def test_pitching_mobile_nav_uses_shared_single_clearance(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    page.goto(f'{coachboard_url}/pitching', wait_until='domcontentloaded')

    nav = page.locator('#cb-global-mobile-nav')
    expect(nav).to_be_visible()
    geometry = nav.evaluate(
        """nav => {
            const rect = nav.getBoundingClientRect();
            const main = document.querySelector('main.container-fluid');
            return {
                navBottom: rect.bottom,
                navHeight: rect.height,
                viewportHeight: window.innerHeight,
                mainPaddingBottom: parseFloat(getComputedStyle(main).paddingBottom) || 0,
            };
        }"""
    )
    assert abs(geometry['viewportHeight'] - geometry['navBottom']) <= 1
    assert geometry['mainPaddingBottom'] >= geometry['navHeight']
    assert geometry['mainPaddingBottom'] - geometry['navHeight'] <= 12
