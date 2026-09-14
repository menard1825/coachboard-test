# CoachBoard UX/UI Feedback: Game Day & Dugout Mode

This document outlines usability feedback and recommendations for the Game Day and Live Game ("Dugout Mode") experience from the perspective of a travel baseball coach. The primary goal is to make the app simple, smart, and efficient for in-game use, whether on a mobile phone or an iPad in landscape mode.

## 1. Navigating Chaos: Referencing the "Planned" Defense
**The Problem:** Live games get chaotic. If a coach spends time planning the defensive rotation before the game, they currently lack a quick way to reference that original plan while in the Live Game view if things start changing on the fly.
**Recommendation:**
* Add a **"View Original Plan" toggle or button** directly in the Live Game UI.
* When activated, this would temporarily show (or highlight) the pre-planned positions for the current inning, allowing the coach to quickly orient themselves without leaving the live scoring/tracking view.

## 2. Streamlining Substitutions: Less "Noise," More Action
**The Problem:** Coaches find the Live Game interface "too busy." While drag-and-drop or tap-to-swap mechanics are generally acceptable, the flow is bogged down by too many prompts or unnecessary friction when making simple moves. Setting up the next inning can also feel too detached from the current inning.
**Recommendation:**
* **Reduce Modal Friction:** When a coach swaps a player (Bench -> Position), eliminate confirmation modals unless absolutely necessary (e.g., enforcing pitcher rest rules). A simple tap-to-swap should immediately execute the move.
* **Unified Interface:** Ensure the UI for "Current Inning" and "Next Inning" setup are visually distinct but functionally identical, reducing cognitive load. Consider a streamlined "Command Center" panel on iPads that keeps the bench and field visible simultaneously.

## 3. Fair Play Visibility: Tracking Bench Time
**The Problem:** Moving players around and tracking who has been sitting on the bench is a top priority, but it currently requires too much effort to monitor during the game.
**Recommendation:**
* **Prominent Bench Metrics:** Display the "Innings Sat" counter directly on the player avatars in the bench area of the Live Game view.
* **Visual Flags:** Use subtle color coding (e.g., a yellow or red border) on the bench to highlight players who have been sitting for 2+ consecutive innings, making it instantly obvious who needs to get into the field next.

## 4. Handling Unplanned Games: The "Blank Slate" Scenario
**The Problem:** Not all coaches plan their games in advance. If a coach starts a game "bare" and figures it out as they go, filling out the entire field from scratch every inning is tedious and slow.
**Recommendation:**
* **"Copy Previous Inning" Button:** For empty innings, provide a one-tap button to duplicate the defensive alignment from the previous inning. The coach can then just make the 1 or 2 necessary swaps instead of assigning 9 players manually.
* **Auto-Fill from Bench (Optional):** A "Smart Fill" button that automatically places benched players into the field based on their primary positions could be a powerful tool for coaches flying by the seat of their pants.

## 5. Terminology and Setup Flow
**The Problem:** The Pre-Game / Game Day dashboard uses buttons like "Open GameChanger Setup" and "Enter GameChanger Stats," which can be slightly confusing or overly verbose.
**Recommendation:**
* Simplify button labels to be action-oriented. For example, use **"Setup Lineup/Defense"** instead of "Open GameChanger Setup" and **"Sync Pitch Counts"** or **"Add Pitch Counts"** instead of "Enter GameChanger Stats."
* Ensure the pre-game checklist provides a clear, traffic-light (Red/Yellow/Green) visual cue for whether a game is actually ready to start.
