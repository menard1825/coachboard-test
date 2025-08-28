import sys
from playwright.sync_api import sync_playwright

# Add the project root to the Python path
sys.path.insert(0, '.')

# --- Test ---
def run_playwright_test():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        try:
            # Navigate to the login page
            page.goto("http://localhost:5002/login", timeout=60000)

            # Fill in the login form and submit
            page.fill("input[name='username']", "Mike1825")
            page.fill("input[name='password']", "password")
            page.click("button[type='submit']")

            # Wait for navigation to the dashboard (or whatever page comes after login)
            page.wait_for_url("http://localhost:5002/", timeout=60000)

            # Navigate to the user management page
            page.goto("http://localhost:5002/users")

            # Click the "Edit" button for a user that is not the admin
            edit_button = page.locator('.user-row:not(:has-text("N/A")) .btn:has-text("Edit")').first()
            edit_button.click()

            # Give the modal time to appear
            page.wait_for_selector(".modal.fade.show", state="visible")

            # Take a screenshot of the page with the modal open
            page.screenshot(path="jules-scratch/verification/verification.png")
            print("Screenshot taken successfully.")

        except Exception as e:
            print(f"An error occurred during Playwright test: {e}")
            page.screenshot(path="jules-scratch/verification/error.png")

        finally:
            browser.close()

if __name__ == '__main__':
    run_playwright_test()
