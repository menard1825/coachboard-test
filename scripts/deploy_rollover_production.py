"""Deploy the reviewed rollover commit on Mike's VM with a recoverable DB upgrade.

Run from the prepared preview checkout using the production virtualenv's Python:
    python scripts/deploy_rollover_production.py --apply EXPECTED_COMMIT

The script fetches and verifies the exact commit before stopping the service. It
backs up the stopped SQLite database and rolls back code and DB on failure.
"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
from urllib.request import urlopen

PROD = Path('/home/mike1825/team-coach-app-dev3')
PREVIEW = Path(__file__).resolve().parents[1]
SERVICE = 'coachboard.service'
BASE = '778a6701709064968c65c806590a6f6465b320a2'
BRANCH = 'fix/prod-team-rollover-20260929'
REVISION = '20260929_team_rollover'


def run(*args, cwd=None):
    return subprocess.run(args, cwd=cwd, check=True, text=True,
                          stdout=subprocess.PIPE).stdout.strip()


def git(path, *args):
    return run('git', '-C', str(path), *args)


def service_is_active():
    return subprocess.run(('systemctl', 'is-active', '--quiet', SERVICE),
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def quote(value):
    return '"' + value.replace('"', '""') + '"'


def snapshot(connection, columns=None):
    if columns is None:
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version'")]
        columns = {table: [row[1] for row in connection.execute(
            'PRAGMA table_info(' + quote(table) + ')')] for table in tables}
    contents = {table: sorted(repr(row) for row in connection.execute(
        'SELECT ' + ','.join(quote(c) for c in names) + ' FROM ' + quote(table)))
        for table, names in columns.items()}
    return columns, contents


def check_database(path, revision):
    with sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True) as connection:
        if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError(f'SQLite integrity check failed: {path}')
        actual = connection.execute('SELECT version_num FROM alembic_version').fetchall()
        if actual != [(revision,)]:
            raise RuntimeError(f'Unexpected database revision: {actual!r}')
        if connection.execute('PRAGMA foreign_key_check').fetchall():
            raise RuntimeError(f'SQLite foreign key check failed: {path}')


def wait_for_app():
    for _ in range(20):
        try:
            if service_is_active():
                with urlopen('http://127.0.0.1:5004/login', timeout=2) as response:
                    if response.status == 200:
                        return
        except (subprocess.CalledProcessError, OSError):
            pass
        time.sleep(1)
    raise RuntimeError('The service did not return a healthy login page on port 5004.')


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
        parser.error('Use the production virtualenv Python to run this script.')
    if PREVIEW.name != 'coachboard-prod-rollover-preview' or not (PREVIEW / 'app.db').is_file():
        parser.error('Run from the prepared, separate preview checkout.')
    if git(PREVIEW, 'rev-parse', 'HEAD') != target:
        parser.error('The preview checkout is not at the expected commit.')
    if git(PROD, 'rev-parse', 'HEAD') != BASE:
        parser.error('Production code changed. Stop and review it first.')
    if git(PROD, 'status', '--porcelain', '--untracked-files=no'):
        parser.error('Production has tracked changes. Stop and review them first.')
    if run('systemctl', 'show', SERVICE, '--property=WorkingDirectory', '--value') != str(PROD):
        parser.error('The named service does not point to the expected production directory.')
    if not service_is_active():
        parser.error('Production service is not active; stop and investigate.')
    check_database(PROD / 'app.db', '61099c75ca7e')

    # Fetch and verify while production is still serving requests.
    git(PROD, 'fetch', '--no-tags', 'origin', BRANCH)
    if git(PROD, 'rev-parse', 'FETCH_HEAD') != target:
        parser.error('Remote branch moved; production was not stopped or modified.')
    run('sudo', '-v')
    backup_dir = Path.home() / 'coachboard-rollover-backups' / datetime.now().strftime('%Y%m%d-%H%M%S')
    backup_dir.mkdir(mode=0o700, parents=True)
    db_backup = backup_dir / 'app.db'
    stopped = False
    changed = False
    try:
        run('sudo', 'systemctl', 'stop', SERVICE)
        stopped = True
        if service_is_active():
            raise RuntimeError('Service is still active; refusing to copy or upgrade the database.')
        with sqlite3.connect('file:' + str(PROD / 'app.db') + '?mode=ro', uri=True) as source:
            with sqlite3.connect(db_backup) as destination:
                source.backup(destination)
        check_database(db_backup, '61099c75ca7e')
        with sqlite3.connect(db_backup) as old:
            columns, before = snapshot(old)
        logos = PROD / 'static' / 'uploads' / 'logos'
        if logos.exists():
            shutil.copytree(logos, backup_dir / 'logos')
        (backup_dir / 'deployment.json').write_text(json.dumps({
            'original_commit': BASE, 'target_commit': target,
            'service': SERVICE, 'production': str(PROD)}, indent=2) + '\n')

        git(PROD, 'checkout', '--detach', target)
        changed = True
        run(sys.executable, '-c',
            "from app import create_app; from flask_migrate import upgrade; "
            "app=create_app(); ctx=app.app_context(); ctx.push(); "
            "upgrade(directory='migrations'); ctx.pop()", cwd=PROD)
        check_database(PROD / 'app.db', REVISION)
        with sqlite3.connect(PROD / 'app.db') as upgraded:
            _, after = snapshot(upgraded, columns)
            if before != after:
                raise RuntimeError('Migration changed existing table values.')
            members = upgraded.execute('SELECT COUNT(*) FROM team_memberships').fetchone()[0]
            users = upgraded.execute('SELECT COUNT(*) FROM users').fetchone()[0]
            if members != users:
                raise RuntimeError('Coach membership backfill count mismatch.')
        run('sudo', 'systemctl', 'start', SERVICE)
        wait_for_app()
        print(f'PRODUCTION READY at {target}. Backup: {backup_dir}', flush=True)
        print('Check login, old games and pitching, team switching, and a saved lineup/defense.', flush=True)
    except Exception:
        if stopped:
            print('Deployment failed; restoring the original code and database.', file=sys.stderr)
            try:
                run('sudo', 'systemctl', 'stop', SERVICE)
                if changed or git(PROD, 'rev-parse', 'HEAD') != BASE:
                    git(PROD, 'checkout', '--detach', BASE)
                if db_backup.is_file():
                    for suffix in ('-wal', '-shm'):
                        (PROD / ('app.db' + suffix)).unlink(missing_ok=True)
                    shutil.copy2(db_backup, PROD / 'app.db')
                run('sudo', 'systemctl', 'start', SERVICE)
                wait_for_app()
                print(f'Original production restored. Backup: {backup_dir}', file=sys.stderr)
            except Exception as restore_error:
                print(f'Automatic restoration FAILED: {restore_error}. Backup: {backup_dir}', file=sys.stderr)
        raise


if __name__ == '__main__':
    main()
