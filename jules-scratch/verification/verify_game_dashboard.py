from playwright.sync_api import sync_playwright, expect

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

        # 2. Navigate to the Games tab
        page.locator('a[href="#games"]').first.click()

        # Take a screenshot to debug the form
        page.screenshot(path="jules-scratch/verification/debug_games_form.png")

        # 3. Fill out the new game form
        page.get_by_label("Date").fill("2025-10-26")
        page.get_by_label("Opponent").fill("Test Opponent")
        page.get_by_role("button", name="Add Game").click()

        # ... rest of the script

    except Exception as e:
        print(f"An error occurred during verification: {e}")
        page.screenshot(path="jules-scratch/verification/error.png")
    finally:
        browser.close()

with sync_playwright() as playwright:
    run(playwright)