from playwright.sync_api import sync_playwright, expect
import re

def run(playwright):
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    try:
        # 1. Log in to the application
        page.goto("http://127.0.0.1:5002/login")
        page.get_by_label("Username").fill("Mike1825")
        page.get_by_label("Password").fill("password")
        page.get_by_role("button", name="Login").click()
        expect(page).to_have_url("http://127.0.0.1:5002/")

        # 2. Navigate to the Games tab and wait for it to be active
        page.locator('a[href="#games"]').first.click()
        games_tab_pane = page.locator("#games")
        # Use a regex to check for the 'active' class, which is more robust
        expect(games_tab_pane).to_have_class(re.compile(r"\bactive\b"))

        # 3. Create a new game, scoping locators to the active tab
        games_tab_pane.get_by_label("Date").fill("2025-10-26")
        games_tab_pane.get_by_label("Opponent").fill("Test Opponent")
        games_tab_pane.get_by_role("button", name="Add Game").click()

        # 4. Verify that the new game page is loaded
        expect(page.get_by_text("vs Test Opponent on Saturday, 10/26/25")).to_be_visible()

        # 5. Verify that "Planning Mode" is visible by default
        expect(page.locator("#planning-mode-container")).to_be_visible()
        expect(page.locator("#live-mode-container")).to_be_hidden()

        # 6. Switch to "Live Mode"
        page.locator("#live-mode-toggle").check()

        # 7. Verify that "Live Mode" is now active
        expect(page.locator("#planning-mode-container")).to_be_hidden()
        expect(page.locator("#live-mode-container")).to_be_visible()
        expect(page.locator("#game-status-badge")).to_have_text("Live")

        # 8. Interact with the scoreboard
        page.locator("#our-score-plus").click()
        page.locator("#our-score-plus").click()
        page.locator("#opponent-score-plus").click()
        page.locator("#outs-plus").click()

        # 9. Verify scoreboard updates
        expect(page.locator("#live-our-score")).to_have_text("2")
        expect(page.locator("#live-opponent-score")).to_have_text("1")
        expect(page.locator("#live-outs")).to_have_text("Outs: 1")

        # 10. Take a screenshot of the live game dashboard
        page.screenshot(path="jules-scratch/verification/game_dashboard_verification.png")
        print("Successfully created screenshot of the live game dashboard.")

    except Exception as e:
        print(f"An error occurred during verification: {e}")
        page.screenshot(path="jules-scratch/verification/error.png")
    finally:
        browser.close()

with sync_playwright() as playwright:
    run(playwright)