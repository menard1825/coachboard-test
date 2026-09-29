"""Deploy a reviewed code-only CoachBoard hotfix without rerunning migrations.

Run from the separate preview checkout with the production virtualenv Python:
    python scripts/deploy_production_hotfix.py --apply EXPECTED_COMMIT
"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys

from deploy_rollover_production import (
    PROD, PREVIEW, SERVICE, BRANCH, run, git, service_is_active,
    check_database, wait_for_app,
)

CURRENT = 'b928a0382501f89e318a8dbbec55006a4d0bd20b'
REVISION = '20260929_team_rollover'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', metavar='EXPECTED_COMMIT', required=True)
    target = parser.parse_args().apply
    if len(target) != 40 or any(c not in '0123456789abcdef' for c in target):
        parser.error('Use the full reviewed 40-character commit SHA.')
    if os.geteuid() == 0:
        parser.error('Run as mike1825; sudo is used only for systemctl.')
    os.umask(0o077)
    if Path(sys.prefix) not in (PROD / 'venv', PROD / '.venv'):
        parser.error('Use the production virtualenv Python.')
    if PREVIEW.name != 'coachboard-prod-rollover-preview' or git(PREVIEW, 'rev-parse', 'HEAD') != target:
        parser.error('The separate preview checkout is not at the reviewed commit.')
    if git(PREVIEW, 'status', '--porcelain', '--untracked-files=no'):
        parser.error('Preview has tracked changes; stop and review them first.')
    if git(PROD, 'rev-parse', 'HEAD') != CURRENT:
        parser.error('Production code changed. Stop and review before updating.')
    if git(PROD, 'status', '--porcelain', '--untracked-files=no'):
        parser.error('Production has tracked changes. Stop and review before updating.')
    if run('systemctl', 'show', SERVICE, '--property=WorkingDirectory', '--value') != str(PROD):
        parser.error('The service does not point to the expected production directory.')
    if not service_is_active():
        parser.error('Production service is not active. Investigate before updating.')
    check_database(PROD / 'app.db', REVISION)

    # All network work and commit verification happen before the service stops.
    git(PROD, 'fetch', '--no-tags', 'origin', BRANCH)
    if git(PROD, 'rev-parse', 'FETCH_HEAD') != target:
        parser.error('Remote branch moved. Production was not stopped.')
    run('sudo', '-v')
    backup_dir = Path.home() / 'coachboard-hotfix-backups' / datetime.now().strftime('%Y%m%d-%H%M%S')
    backup_dir.mkdir(mode=0o700, parents=True)
    backup = backup_dir / 'app.db'
    stopped = False
    try:
        run('sudo', 'systemctl', 'stop', SERVICE)
        stopped = True
        if service_is_active():
            raise RuntimeError('Service is still active; refusing to update code.')
        with sqlite3.connect('file:' + str(PROD / 'app.db') + '?mode=ro', uri=True) as source:
            with sqlite3.connect(backup) as destination:
                source.backup(destination)
        check_database(backup, REVISION)
        (backup_dir / 'deployment.json').write_text(json.dumps({
            'original_commit': CURRENT, 'target_commit': target,
            'service': SERVICE, 'production': str(PROD)}, indent=2) + '\n')

        git(PROD, 'checkout', '--detach', target)
        # Code-only update: the live database stays in place, including new players.
        check_database(PROD / 'app.db', REVISION)
        run('sudo', 'systemctl', 'start', SERVICE)
        wait_for_app()
        print(f'HOTFIX READY at {target}. Fresh backup: {backup_dir}', flush=True)
    except Exception:
        if stopped:
            print('Hotfix failed; restoring the previous code and database.', file=sys.stderr)
            try:
                run('sudo', 'systemctl', 'stop', SERVICE)
                git(PROD, 'checkout', '--detach', CURRENT)
                if backup.is_file():
                    for suffix in ('-wal', '-shm'):
                        (PROD / ('app.db' + suffix)).unlink(missing_ok=True)
                    shutil.copy2(backup, PROD / 'app.db')
                run('sudo', 'systemctl', 'start', SERVICE)
                wait_for_app()
                print(f'Previous production restored. Backup: {backup_dir}', file=sys.stderr)
            except Exception as restore_error:
                print(f'Automatic restoration FAILED: {restore_error}. Backup: {backup_dir}', file=sys.stderr)
        raise


if __name__ == '__main__':
    main()
