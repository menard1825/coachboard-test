# CoachBoard browser testing

CoachBoard's Playwright suite runs in GitHub Actions with a disposable SQLite
database. It never reads or writes the production database.

## Automatic runs

Every push and pull request runs the existing compile, migration, and pytest
checks first. If those pass, the Playwright job installs Chromium and exercises
the critical browser flows. Failed browser runs retain screenshots, video, and
a Playwright trace in the `coachboard-playwright-results` workflow artifact.

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
