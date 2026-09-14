# CoachBoard browser testing

CoachBoard's Playwright suite runs in GitHub Actions with a disposable SQLite
database. It never reads or writes the production database.

## Automatic runs

Every push and pull request runs the existing compile, migration, and pytest
checks first. If those pass, the Playwright job installs Chromium and exercises
the app-wide browser suite. Failed browser runs retain screenshots, video, and
a Playwright trace in the `coachboard-playwright-results` workflow artifact.

## App-wide coverage

The disposable test database includes multiple teams, coach roles, players,
games, templates, pitching history, scouting records, practices, development
items, coach notes, and signs. The suite covers:

- all public account pages and all authenticated CoachBoard screens;
- every dashboard area and JSON data service;
- roster, pitcher profile, player order, lineup, and defensive template CRUD;
- scouting, player development, lessons, coach notes, practices, tasks,
  attendance, signs, pitching outings, targets, and validation;
- Game Day scheduling, game notes, absences, per-game rules, readiness, reports,
  and cleanup;
- Live Game start, defense and pitcher changes, next-inning preparation, clock,
  inning advance, undo, end-game, postgame pitching, and legacy-client safety;
- user, team, settings, registration, password, role, team-switching, and
  cross-team access controls;
- desktop and phone-size navigation; and
- clean non-500 handling for the remaining route contracts and missing records.

This is comprehensive workflow coverage rather than a claim that every possible
data combination can be exhausted. Add a focused regression test whenever a new
feature or production bug is introduced.

## Run locally (optional)

Install the development dependencies and Chromium once:

```bash
python -m pip install -r requirements-dev.txt
python -m playwright install --with-deps chromium
```

Run the normal regression suite:

```bash
python -m pytest -q
```

Run the browser suite:

```bash
COACHBOARD_E2E=1 python -m pytest -q tests/e2e --browser chromium
```

To watch the browser, append `--headed --slowmo 300`. The suite starts and
stops its own local server and creates its own temporary database.
