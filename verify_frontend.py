import time
from playwright.sync_api import sync_playwright

def verify_rules():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        page.goto("http://localhost:5002/login")
        page.fill("input[name='username']", "Mike1825")
        page.fill("input[name='password']", "password")
        page.click("button[type='submit']")

        page.wait_for_load_state('networkidle')

        # Go to settings to set rule set to MLB Pitch Smart if needed
        page.goto("http://localhost:5002/admin/settings")
        # Change Pitching Rule Set to MLB Pitch Smart and Age to 12U
        page.click("a[href='#pitching-rules-settings']")
        page.select_option("select[name='pitching_rule_set']", "MLB Pitch Smart")
        page.select_option("select[name='age_group']", "12U")
        page.locator("div#pitching-rules-settings button[type='submit']").click()
        page.wait_for_load_state('networkidle')

        page.goto("http://localhost:5002/rules")
        page.wait_for_load_state('networkidle')

        page.screenshot(path="screenshot_rules.png", full_page=True)

        browser.close()

if __name__ == "__main__":
    verify_rules()
