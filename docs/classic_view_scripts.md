# Game page scripts: Classic and Updated

Every script that runs on `/game/<id>`, what kind of code it is, and whether
Classic Prepare Game loads it. A coach's view is decided in `ui_view.py`.

- **Classic** is Prepare Game only.
- **Updated** is the default.
- A live game, and a completed game's own tools (`?pitching=1`, `?edit=1`),
  are always Updated.

## Kinds of code

- **Shared behavior:** saves, permissions, validation, Start Game and
  conflict handling. Loaded in both views, so both views read and write the
  same game data the same way.
- **Updated-only presentation:** the Updated screens. Not loaded in Classic.
- **Mixed:** a script that holds both kinds. Each one was either split, or
  made to draw only into Updated's own markup.
- **Live game:** always Updated. Classic never loads it, because a live game
  reloads into Updated.

Scripts reach the page by four routes:
- the template (`templates/game_management.html`);
- the base template;
- `navigation_v2.js` / `coachboard_ui.js`, which load further scripts;
- the response hooks in `blueprints/live_game_ui.py` and
  `blueprints/live_game_bulk_api.py`, which add scripts to the HTML.

Classic is handled on each route: a template branch, a `navigation_v2.js`
branch, and `ui_view.is_classic_page()` in both hooks.

## Shared behavior (both views)

| Script | What it does | Notes for Classic |
|---|---|---|
| `pregame_rotation_sync.js` | The single pregame defense writer: one `/save_rotation` queue. Newest edit wins; a failed save stays visible and can be retried; a stale server refresh never overwrites a newer local edit. | The only writer on either page. Switching views or devices reloads the page, so there is never a second writer. |
| `game_logic.js` | The original editor: inning tabs, + / − inning, Copy Previous, More Tools (copy to innings, clear), Menu (print, templates, delete), desktop drag (Sortable), tap a position to Assign Player, Rotation Matrix, Playing Time Summary, bench report. Also the socket refresh. | Saves only through the queue above. A planned player marked Out is drawn, marked Out, so a drag can't drop them silently. Names and positions are escaped. Its old live-mode handlers stay dormant, because live is always Updated. |
| `lineup_editor.js` | The batting order editor (a draft; saves with `/edit_lineup` or `/add_lineup`). | Unchanged. |
| `start_game_flow.js` | **Start Game**, moved unchanged out of `live_game_contract.js`. It settles the save queue first and sends the reviewed 1st inning. The server's hard stops, open-position and starting-pitcher questions are asked the same way in both views. It also owns the open-position acknowledgements (`CBRecordAcks`). | Classic's "fix it" helpers point to the original diamond. |
| `game_prep_readiness.js` | **Mixed.** The 5-second readiness feed (`coachboard:readiness`), plus Updated's checklist panel. | Loaded in Classic as the feed. Its panel draws only into Updated's `#pregame-checklist-container`, which Classic doesn't have. |
| `prepare_game_notices.js` | The Out-player notice: "Mark Playing" or "Remove from plan" (through the existing writers), and the rules notice. | In Classic it sits in the Game Day strip. Classic states the rules notice itself, beside the Pitcher Availability table. |
| `game_pitching_rule_picker.js` | **Mixed.** The game's pitching rules (Start Game's "Choose Rules"), plus Updated's eligibility cards. | **Split.** In Classic it keeps the original Pitcher Availability table. A rule change reloads the page, so the table is always the server's. |
| `fair_play_assistant.js` | Fair Play status, read from the Rotation Matrix (only when the team uses Fair Play rules). | Loaded by `coachboard_ui.js` on every game page. |
| `ui_view_switch.js` | The account menu's view switch. It never leaves a page with an unsaved form, an open window, or a save in flight or failed. | Waits for the save queue on both views. |
| `client_timezone.js`, `coachboard_ui.js`, `navigation_v2.js` | The app shell. | **`navigation_v2.js` is mixed:** on a Classic game page it loads only the rules picker. |

## Classic only

| File | What it does |
|---|---|
| `templates/_game_management_classic.html` | The production page (`ee4e9dd`): Back to All Games bar, Player Availability and Batting Lineup side by side, Defensive Rotation (`_rotation_editor.html`), Pitching Log (`_pitching_log.html`). It uses the same ids as Updated, so the shared scripts work unchanged. |
| `classic_prepare_game.js` | The Game Day strip: Start Live Game (`CBStartGame`), the readiness reasons, the save status (from the queue, with Retry), the Out marks on the cards, and the hand-off to the live screens once the game is live. Presentation only. |
| `static/css/classic_view.css` | Restores the original light game bar and styles the strip, Out players and the "Choose Another Pitcher" highlight. The diamond, tags and matrix use the original `main.css`. |

## Updated-only presentation (not loaded in Classic)

| Script | What it is |
|---|---|
| `game_management_visual_polish.js`, `game_management_team_theme_availability.js`, `game_management_coach_simplify.js` | Updated's layout and theme layers over the shared markup. |
| `live_game_board_prep.js` | Updated's tap field (`#pregame-defense-editor-v3`) and its saved defenses. It writes through the same queue. |
| `pregame_defense_picker_clarity.js`, `assignment_picker_availability.js`, `future_pitcher_tbd.js` | The tap field's picker. |
| `game_setup_ux.js` | **Mixed:** Updated's Start Game box, availability switches and pitching-plan card. Classic shows its own Start strip from the same readiness. |
| `pregame_quick_start.js`, `pregame_quick_start_modals.js`, `pregame_starting_defense_scope.js` | Updated's guided setup. |
| `previous_game_setup.js` | "Use Previous Game Setup" (Updated for now). |
| `live_game_clock.js` | Prepare Game's Game Clock card (Set Time Limit). Updated for now; the clock itself starts with the live game. |
| `postgame_game_management_cleanup.js` | A completed game's tools, which are always Updated. |
| `static/css/coachboard_pages.css` boot guard | Hides the page until Updated's tap field is built. **Split:** it doesn't apply to Classic. |

## Live game (always Updated; not loaded in Classic)

- `live_game_v2.js`, `live_game_contract.js` (minus Start Game),
  `live_game_coach_ui.js`, `live_game_field_realism.js`,
  `gameday_pitching_steppers.js`, `live_game_unified_field_entry.js`,
  `live_game_inning_clarity.js`;
- from the response hooks: `live_game_feedback_pass.js`,
  `live_game_modal_focus.js`, `live_game_drag_controller.js`,
  `live_game_pitching_finalize.js`, `live_game_pitcher_change_complete.js`,
  `live_game_board_prep_v2.js`, `live_game_postgame_cleanup.js`;
- loaded by those: `live_game_sync_status.js`, `live_game_clock_controls.js`,
  `live_game_bench_report.js`, `live_game_dugout_mode.js`,
  `live_game_command_center.js`, `live_game_connection_status.js`.

## Never disabled

The same server rules apply to every save from either view:
- the game write lock;
- refusing pregame saves once the game is live (409);
- refusing a player placed twice;
- Start Game's checks;
- the security guard.

Classic adds no write path of its own.
