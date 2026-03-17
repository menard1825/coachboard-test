from playwright.sync_api import sync_playwright
import time

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("http://localhost:5002/login")

        # Ensure login
        page.fill('input[name="username"]', 'Mike1825')
        page.fill('input[name="password"]', 'password')
        page.click('button[type="submit"]')

        # Wait for the next page to load instead of hardcoding the URL
        time.sleep(2)

        # Navigate to Admin Settings
        page.goto("http://localhost:5002/admin/settings")
        page.wait_for_selector('a[href="#season-management"]')

        # Click Season Management tab
        page.click('a[href="#season-management"]')
        page.wait_for_selector('button[data-bs-target="#startNewSeasonModal"]')

        # Click "Configure New Season"
        page.click('button[data-bs-target="#startNewSeasonModal"]')

        # Wait for modal to become visible
        page.wait_for_selector('#startNewSeasonModal', state='visible')
        time.sleep(1) # Extra second for bootstrap animation

        # Take a screenshot of the modal before typing
        page.screenshot(path="screenshot_modal_empty.png")

        # Type "START NEW SEASON"
        page.fill('#confirmText', 'START NEW SEASON')

        # The button should become enabled
        page.wait_for_selector('#confirmResetBtn:not([disabled])')
        time.sleep(1)

        # Take a screenshot
        page.screenshot(path="screenshot_modal_filled.png")

        browser.close()

if __name__ == '__main__':
    run()
