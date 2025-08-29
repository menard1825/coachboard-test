import time
from playwright.sync_api import sync_playwright, expect

def run_verification(playwright):
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    try:
        # Set a default timeout for all actions
        page.set_default_timeout(10000) # 10 seconds

        # 1. Log in as the admin user
        page.goto("http://localhost:5002/login")
        page.get_by_label("Username").fill("Mike1825")
        page.get_by_label("Password").fill("password")
        page.get_by_role("button", name="Login").click()

        # Wait for navigation to the home page (which is the roster)
        expect(page.get_by_role("heading", name="Current Roster")).to_be_visible()

        # 2. Add players to the roster
        for i in range(1, 11):
            # Click the "New Player" button to show the modal
            page.get_by_role("button", name="New Player").click()

            # Get the modal by its ID
            modal = page.locator("#addPlayerModal")
            expect(modal).to_be_visible()

            # Fill the form inside the modal using name attributes as selectors
            modal.locator('input[name="name"]').fill(f"Player {i}")
            modal.locator('input[name="number"]').fill(str(i))
            modal.get_by_role("button", name="Add Player").click()

            # Wait for the modal to disappear
            expect(modal).not_to_be_visible()

            # Wait for the player to appear in the list
            expect(page.get_by_text(f"Player {i}")).to_be_visible()

        # 3. Open the lineup editor
        page.get_by_role("button", name="Edit Lineup").click()

        # Wait for the modal to be visible
        lineup_modal = page.locator("#lineupEditorModal")
        expect(lineup_modal).to_be_visible()

        # 4. Drag a player
        bench_list = lineup_modal.locator("#lineup-bench")
        order_list = lineup_modal.locator("#lineup-order")

        # Get a player to drag (e.g., Player 5)
        player_to_drag = bench_list.get_by_text("Player 5")

        # Get the drop target (the batting order list)
        order_box = order_list.bounding_box()

        # Start the drag from the player's location
        player_to_drag.hover()
        page.mouse.down()

        # Move the mouse to the third position in the order list
        page.mouse.move(order_box['x'] + order_box['width'] / 2, order_box['y'] + 75)

        # 5. Take a screenshot during the drag
        time.sleep(0.5)
        page.screenshot(path="jules-scratch/verification/lineup_drag_verification.png")

        # Complete the drag
        page.mouse.up()

        print("Verification script completed successfully.")

    except Exception as e:
        print(f"An error occurred: {e}")
        page.screenshot(path="jules-scratch/verification/error.png")
        # Reraise the exception to make it clear the script failed
        raise
    finally:
        browser.close()

with sync_playwright() as p:
    run_verification(p)
