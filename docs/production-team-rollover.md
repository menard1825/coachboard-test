# Production team rollover

Base: `778a6701709064968c65c806590a6f6465b320a2` (`hotfix/prod-ipad-defense-save-20260828`).
This branch is for the existing Flask production app, independently of Test App 2.

## Behavior

- **Teams & Seasons** appears below the team header on desktop and mobile.
- A head coach selects returning players and existing coaches, names the new team and season, and chooses its age group. Their own access is included automatically.
- The team may keep its name across seasons; the same name and season pair is rejected to avoid an accidental duplicate.
- Player profiles/notes, colors, coaching settings, and optionally signs carry over. Upload a logo separately: the existing uploader deletes its previous file, so sharing the old logo path would endanger the old team.
- Schedules, game lineups, defense plans, attendance, pitching logs, and development records stay with the original team. New season totals begin empty.
- Explicitly linked player profiles share pitching workload for availability calculations, including subsequent changes and a second rollover. Matching names never link unrelated players. The app continues using its existing pitching rule calculation; this change does not implement new USSSA rules.
- Coaches switch using the same account. The last selected team is remembered at the next login. Roles and roster ordering belong to the selected team.
- Archive/restore players instead of deleting their history. Archived players are excluded from active planning; past games and statistics retain their records.
- Optionally archive the original team as read-only. A head coach can restore it by confirming its name.
- New team and membership writes are atomic; a unique submission key prevents replay creating another team.
- Saves are bound to the team shown on the page and protected by a form token. Old tabs receive a reload message after a team switch. Legacy destructive links now submit POST forms.
- Live updates are sent only to the matching team's room. Removing a coach disconnects their live connection for that team.

The first release concentrates on rollover and safe everyday use. The existing lineup/defense template workflow remains available. A new “use previous game” shortcut is not part of this patch.

## Database upgrade

New revision: `20260929_team_rollover`, from `61099c75ca7e`.
It adds team season/archive metadata, player active/identity fields, and a membership table backfilled from existing users. Existing rows are retained. There are no production dependencies added.

Do **not** stamp an unexpected database revision or run `db.create_all()` on production.
The preview preparation script checks the revision, SQLite integrity, and foreign keys. It compares every original column value in every original table before/after migration.

## Preview first

Clone this branch into `/home/mike1825/coachboard-prod-rollover-preview`, verify the supplied commit, then use the production virtualenv's Python to run:

```bash
python scripts/prepare_rollover_preview.py /home/mike1825/team-coach-app-dev3
python scripts/run_rollover_preview.py
```

The source DB is opened in SQLite read-only mode and copied with the backup API, including committed WAL data. The script refuses to overwrite a preview database. Uploaded logos are copied, never moved. Preview prefers port 5006, chooses an available port if needed, and prints its URL. It uses a separate cookie and a random secret with the existing coach accounts from the copy. Changes in the preview are disposable and **must not** be copied back over production.

Review the returning-player list; create a sample new season; switch to the old team; confirm its games and pitching history; check game saves and archive/restore a sample player. Stop the preview with Ctrl+C.

## Production deployment gate

Before changing the live app, verify the real database preview passed, review the UI, identify the exact systemd unit, and verify the app's configured session secret. Then:

1. Recheck production HEAD and tracked changes. Leave untracked backups, logs, and uploaded logos alone.
2. Stop the verified production service for the migration window.
3. Take a fresh SQLite backup and preserve the current code commit and uploaded files. Do not use the older preview database.
4. Check out the exact reviewed commit, run `flask --app 'app:create_app()' db upgrade` with the production environment, and verify integrity, preserved old values, and memberships.
5. Start the same production service. Verify login, the current roster, old games, pitching, a saved lineup and defense plan, and Teams & Seasons.
6. Reload all open app tabs after deployment; old forms do not have the new request tokens.

Rollback: stop the service, restore the fresh pre-deployment database backup and original code commit, then restart. A schema downgrade is deliberately blocked because dropping memberships after rollover would disconnect histories. A rollback after users have entered new data requires preserving/reconciling those writes first.

## Validation commands

```bash
python -m pytest -q tests/test_production_rollover.py
python -m pytest -q tests/test_production_rollover_browser.py
```

Browser tests require Playwright Chromium and the exact CDN assets already used by production. `COACHBOARD_TEST_VENDOR` optionally points to extracted `npm pack` packages for Bootstrap 5.3.3, Bootstrap Icons 1.11.3, Socket.IO client 4.7.5, and SortableJS 1.15.0 when the test browser cannot reach the CDNs. These are real assets, not mocks. No vendor assets are added to production.
