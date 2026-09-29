"""Copy the live DB read-only into this isolated checkout and verify its migration.

Run from a separate checkout with the production virtualenv's Python:
    python scripts/prepare_rollover_preview.py /home/mike1825/team-coach-app-dev3
Never run this script inside the production checkout.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE = '778a6701709064968c65c806590a6f6465b320a2'


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def snapshot(conn, columns=None):
    if columns is None:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version'")]
        columns = {table: [r[1] for r in conn.execute('PRAGMA table_info(' + quote(table) + ')')] for table in tables}
    fingerprints = {}
    for table, names in columns.items():
        rows = conn.execute('SELECT ' + ','.join(quote(n) for n in names) + ' FROM ' + quote(table)).fetchall()
        serialized = sorted(json.dumps(row, default=str) for row in rows)
        fingerprints[table] = (len(rows), hashlib.sha256('\n'.join(serialized).encode()).hexdigest())
    return columns, fingerprints


def main():
    if len(sys.argv) != 2:
        raise SystemExit('Usage: prepare_rollover_preview.py /path/to/production')
    production = Path(sys.argv[1]).resolve()
    if production == ROOT or production in ROOT.parents:
        raise SystemExit('The preview must be in a separate checkout, outside production.')
    source = production / 'app.db'
    target = ROOT / 'app.db'
    if not source.is_file() or target.exists():
        raise SystemExit('Production app.db must exist; preview app.db must not already exist. No files were overwritten.')
    head = subprocess.check_output(['git', '-C', str(production), 'rev-parse', 'HEAD'], text=True).strip()
    if head != BASE:
        raise SystemExit('Production HEAD changed. Stop and review before preparing the preview.')
    if subprocess.check_output(['git', '-C', str(production), 'status', '--porcelain', '--untracked-files=no'], text=True).strip():
        raise SystemExit('Production has tracked changes. Stop and review them first.')
    os.umask(0o077)
    with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as live:
        with sqlite3.connect(target) as copy:
            live.backup(copy)
    with sqlite3.connect(target) as copy:
        if copy.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise SystemExit('The copied database failed integrity_check. Production was not changed.')
        revision = copy.execute('SELECT version_num FROM alembic_version').fetchall()
        if revision != [('61099c75ca7e',)]:
            raise SystemExit(f'Unexpected migration revision {revision!r}; do not stamp or upgrade production.')
        columns, before = snapshot(copy)
    from app import create_app
    from flask_migrate import upgrade
    app = create_app({'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + str(target), 'SOCKETIO_ASYNC_MODE': 'threading'})
    with app.app_context():
        upgrade(directory=str(ROOT / 'migrations'))
    with sqlite3.connect(target) as copy:
        _, after = snapshot(copy, columns)
        if before != after:
            raise SystemExit('Migration changed existing data. Stop here; production was not changed.')
        if copy.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise SystemExit('Migration integrity check failed.')
        violations = copy.execute('PRAGMA foreign_key_check').fetchall()
        if violations:
            raise SystemExit(f'Foreign key check found {len(violations)} problems; stop for review.')
        count = copy.execute('SELECT COUNT(*) FROM team_memberships').fetchone()[0]
        users = copy.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        if count != users:
            raise SystemExit('Coach membership backfill count mismatch.')
    uploads = production / 'static' / 'uploads' / 'logos'
    if uploads.exists():
        shutil.copytree(uploads, ROOT / 'static' / 'uploads' / 'logos', dirs_exist_ok=True)
    print('PREVIEW READY: migration passed; every original table and value is preserved.')
    print(f'Coach memberships created: {count}. Production code, database, and services were not changed.')
    # Find the production service name without printing its environment or command line.
    try:
        units = subprocess.check_output(['systemctl','list-units','--type=service','--all','--no-legend','--plain'], text=True)
        matches = []
        for line in units.splitlines():
            fields = line.split()
            if not fields or not fields[0].endswith('.service'):
                continue
            unit = fields[0]
            wd = subprocess.check_output(['systemctl','show',unit,'--property=WorkingDirectory','--value'],text=True).strip()
            if wd == str(production):
                matches.append(unit)
        print('Production service candidates: ' + (', '.join(matches) or 'none found by WorkingDirectory'))
    except (OSError, subprocess.CalledProcessError):
        print('Production service discovery unavailable; service name still needs verification.')


if __name__ == '__main__':
    main()
