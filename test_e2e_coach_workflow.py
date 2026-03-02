from playwright.sync_api import sync_playwright, expect
import os

def test_coach_workflow():
    with sync_playwright() as p:
        # Launch browser. Set headless=False to view the browser window if running locally.
        browser = p.chromium.launch(headless=True)
        # Use desktop dimensions since we're simulating a coach on a computer
        context = browser.new_context(viewport={'width': 1280, 'height': 800})
        page = context.new_page()

        try:
            print("Step 1: Logging in...")
            page.goto("http://localhost:5002/login")
            page.fill("input[name='username']", "Mike1825")
            page.fill("input[name='password']", "password")
            page.click("button[type='submit']")
            page.wait_for_url("http://localhost:5002/")
            print("Login successful.")

            print("Step 2: Adding a new player...")
            # Click Roster tab (desktop navigation)
            page.click("#mainTabsDesktop a[href='#roster']")
            page.wait_for_selector("#roster", state="visible")

            # Click Add Player button
            page.click("button[data-bs-target='#addPlayerModal']")
            page.wait_for_selector("#addPlayerModal", state="visible")

            # Fill in player details
            new_player_name = "E2E Test Player"
            page.fill("#addPlayerModal input[name='name']", new_player_name)
            page.fill("#addPlayerModal input[name='number']", "42")

            # Select positions
            page.wait_for_selector("#addPlayerModal select[name='position1']", state="attached")
            page.select_option("#addPlayerModal select[name='position1']", "CF")
            page.select_option("#addPlayerModal select[name='position2']", "P")
            page.select_option("#addPlayerModal select[name='throws']", "Right")
            page.select_option("#addPlayerModal select[name='bats']", "Left")

            # Submit the form
            page.click("#addPlayerModal button[type='submit']")

            # Wait for the modal to close and the success notification/reload
            page.wait_for_load_state("networkidle")
            print("New player added.")

            # Look for the new player in the Roster tab
            page.click("#mainTabsDesktop a[href='#roster']")
            page.wait_for_selector("#roster", state="visible")
            expect(page.locator("#roster").get_by_text(new_player_name)).to_be_visible()

            # Step 3: Edit the newly added player
            print("Step 3: Editing the player...")
            # Find the player card header and click it to expand
            player_card = page.locator(".player-card").filter(has_text=new_player_name)
            player_card.locator(".card-header").click()

            # Wait for the collapse to open (the form fields become visible)
            expect(player_card.locator("input[name='number']")).to_be_visible()

            # Change the player's number in the expanded form
            player_card.locator("input[name='number']").fill("99")

            # Click the Save button within that card
            player_card.locator(".save-player-btn").click()

            # Wait for the "Saved!" text to appear on the button
            expect(player_card.locator(".save-player-btn")).to_have_text("Saved!")
            print("Player edited.")


            print("Step 4: Creating a practice plan...")
            page.click("#mainTabsDesktop a[href='#practice_plan']")
            page.wait_for_selector("#practice_plan", state="visible")

            page.fill("#practice_plan input[name='plan_date']", "2024-06-01")
            page.fill("#practice_plan input[name='general_notes']", "E2E Test Practice Plan Notes")
            page.fill("#practice_plan textarea[name='emphasis']", "Hitting and Fielding")
            page.click("#practice_plan form[action*='add_practice_plan'] button[type='submit']")
            page.wait_for_load_state("networkidle")

            page.click("#mainTabsDesktop a[href='#practice_plan']")
            page.wait_for_selector("#practice_plan", state="visible")
            expect(page.locator("#practice_plan").get_by_text("E2E Test Practice Plan Notes").first).to_be_visible()
            print("Practice plan created.")


            print("Step 5: Creating a new game...")
            page.click("#mainTabsDesktop a[href='#games']")
            page.wait_for_selector("#games", state="visible")

            page.fill("input[name='game_date']", "2024-06-15")
            page.fill("input[name='game_opponent']", "E2E Test Opponent")
            page.click("form[action*='add_game'] button[type='submit']")

            # Adding a game redirects to the game management view
            page.wait_for_url("**/game/**", timeout=5000)
            print("New game created.")

            print("Step 6: Verifying Game Management View...")
            expect(page.get_by_text("E2E Test Opponent").first).to_be_visible()
            print("Game management view verified.")

            # Take a final screenshot
            os.makedirs("verification", exist_ok=True)
            page.screenshot(path="verification/e2e_coach_workflow_success.png")
            print("Workflow complete! Screenshot saved to verification/e2e_coach_workflow_success.png")

        except Exception as e:
            print(f"Test failed: {e}")
            os.makedirs("verification", exist_ok=True)
            page.screenshot(path="verification/e2e_coach_workflow_failed.png")
            raise e
        finally:
            browser.close()

if __name__ == "__main__":
    test_coach_workflow()
