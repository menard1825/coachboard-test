
from playwright.sync_api import sync_playwright, expect
import time

def verify_assign_modal_positions():
    """
    Verifies that the 'Assign to [Position]' modal displays player positions
    next to their names (e.g., 'Player Name (Pos1, Pos2)').
    """
    with sync_playwright() as p:
        # Launch browser
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 390, 'height': 844}, # iPhone 12 Pro dimensions
            user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 14_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0.3 Mobile/15E148 Safari/604.1'
        )
        page = context.new_page()

        try:
            # 1. Login
            print("Logging in...")
            page.goto("http://localhost:5002/login")
            page.fill("input[name='username']", "Mike1825")
            page.fill("input[name='password']", "password")
            page.click("button[type='submit']")
            page.wait_for_url("http://localhost:5002/")
            print("Login successful.")

            # 2. Add a player
            print("Navigating to Roster...")
            # Use data attributes or more specific selectors to avoid ambiguity
            # The "New Player" button triggers the modal. It's in the Roster tab which is the default active tab.

            # Wait for the roster tab to be active and visible
            # Note: The tabs are always in DOM, but visibility changes with class.

            print("Adding test player...")
            # The button has data-bs-target="#addPlayerModal"
            page.click("button[data-bs-target='#addPlayerModal']")

            page.wait_for_selector("#addPlayerModal", state="visible")
            page.fill("#addPlayerModal input[name='name']", "Test Player")
            page.fill("#addPlayerModal input[name='number']", "99")

            # Use specific selectors for the position selects to avoid ambiguity or timeout
            # Based on templates/roster.html macro position_select(name, id, ...)
            # id is usually same as name.
            # name="position1", id="position1" (or similar generated id)

            # Wait for the select to be attached
            page.wait_for_selector("#addPlayerModal select[name='position1']", state="attached")

            page.select_option("#addPlayerModal select[name='position1']", "SS")
            page.select_option("#addPlayerModal select[name='position2']", "P")
            page.select_option("#addPlayerModal select[name='position3']", "OF")

            page.click("#addPlayerModal button[type='submit']")
            print("Test player added.")

            # Wait for reload or update. The form submission reloads the page.
            page.wait_for_load_state("networkidle")

            # 3. Create a Game
            print("Creating game...")
            # Navigate to Games tab
            # On mobile, the tabs are in the bottom nav.
            # The bottom nav uses href="#games"
            # Use a selector that targets the mobile bottom nav link
            # .bottom-nav-fixed a[href='#games']
            page.click(".fixed-bottom a[href='#games']")

            # Click Add Game
            # It's inside the #games tab pane
            page.wait_for_selector("#games", state="visible")

            # Fill the add game form directly (it's not a modal in the template provided, it's a card body)
            # <form action="{{ url_for('gameday.add_game') }}" ...>
            page.fill("input[name='game_date']", "2024-05-20")
            page.fill("input[name='game_opponent']", "Test Opponent")
            # Submit game form
            page.click("form[action*='add_game'] button[type='submit']")

            # 4. Navigate to Game Management
            print("Navigating to Game Management...")
            # After adding, it redirects to the game page.
            page.wait_for_url("**/game/**", timeout=5000)

            # 5. Open Assign Modal (Mobile View)
            print("Opening Assign Modal...")

            # Wait for the rotation editor to load.
            # The dropzones in mobile are `pos-mobile-P`, etc.
            # We need to scroll down to see them maybe?
            page.wait_for_selector("#pos-mobile-C", state="visible")

            # Click the Catcher position to open the assign modal
            page.click("#pos-mobile-C")

            # 6. Verify Content
            print("Verifying modal content...")
            # Wait for modal
            page.wait_for_selector("#assignPlayerModal", state="visible")

            # Check for the test player with formatted positions
            # Expected text: "Test Player (SS, P, OF)"
            expect(page.get_by_text("Test Player (SS, P, OF)")).to_be_visible()

            print("SUCCESS: Player with positions found!")

            # 7. Screenshot
            page.screenshot(path="/home/jules/verification/assign_modal_mobile.png")
            print("Screenshot saved.")

        except Exception as e:
            print(f"Test failed: {e}")
            page.screenshot(path="/home/jules/verification/failed_test.png")
            raise e
        finally:
            browser.close()

if __name__ == "__main__":
    verify_assign_modal_positions()
