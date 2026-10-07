"""Split the browser suite into shards by whole test file, for CI.

    python tests/e2e/shard.py files SHARD TOTAL
        Collect tests/e2e and print the test files of shard SHARD (1-based)
        of TOTAL, one per line, for `pytest $(...)`.

    python tests/e2e/shard.py verify TOTAL JUNIT_DIR
        Collect tests/e2e again and check the shards' JUnit files: every
        collected test ran exactly once, and nothing else ran. Prints each
        shard's counts and every failing test's ID. Exits 1 on any
        difference.

Files are never split: each runs whole, in its usual order, on one shard
with its own server and database. Assignment is deterministic -- the
largest file (by collected tests) goes to the least-loaded shard, ties
broken by shard number and file name -- so every shard computes the same
split from the same collection, independently. Collection failing is an
error, never an empty shard.
"""

import collections
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SUITE = 'tests/e2e'
# The same options the shards run with, so test IDs match.
COLLECT_ARGS = ['--browser', 'chromium']


def assign(file_counts, total):
    """{file: tests} -> {file: shard (1..total)}. Pure and deterministic."""
    if total < 1:
        raise ValueError('total must be at least 1')
    loads = [0] * total
    owner = {}
    for path, count in sorted(file_counts.items(), key=lambda item: (-item[1], item[0])):
        shard = min(range(total), key=lambda index: (loads[index], index))
        owner[path] = shard + 1
        loads[shard] += count
    return owner


def parse_collection(output):
    """Test IDs from `pytest --collect-only -q` output."""
    return [line.strip() for line in output.splitlines() if '::' in line and not line.startswith(' ')]


def collect():
    env = dict(os.environ, COACHBOARD_E2E='1')
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', '--collect-only', '-q', '-p', 'no:cacheprovider',
         *COLLECT_ARGS, SUITE],
        cwd=ROOT, env=env, capture_output=True, text=True,
    )
    ids = parse_collection(result.stdout)
    if result.returncode != 0 or not ids:
        sys.stderr.write(result.stdout[-4000:] + result.stderr[-4000:])
        raise SystemExit(f'Collecting {SUITE} failed (exit {result.returncode}, {len(ids)} tests).')
    if len(ids) != len(set(ids)):
        raise SystemExit('Collection returned the same test ID twice.')
    return ids


def file_counts(ids):
    return collections.Counter(test_id.split('::', 1)[0] for test_id in ids)


def junit_id(classname, name):
    """A JUnit testcase back to its pytest ID: tests.e2e.test_x(.Class) + name."""
    parts = classname.split('.')
    for cut in range(len(parts), 0, -1):
        path = '/'.join(parts[:cut]) + '.py'
        if (ROOT / path).is_file():
            return '::'.join([path, *parts[cut:], name])
    return f'{classname}::{name}'


def read_junit(directory):
    """{shard file: [(test id, outcome)]} from every JUnit XML under directory."""
    runs = {}
    for xml in sorted(Path(directory).rglob('*.xml')):
        cases = []
        for case in ET.parse(xml).getroot().iter('testcase'):
            tags = {child.tag for child in case}
            outcome = ('failed' if tags & {'failure', 'error'}
                       else 'skipped' if 'skipped' in tags else 'passed')
            cases.append((junit_id(case.get('classname', ''), case.get('name', '')), outcome))
        runs[str(xml.relative_to(directory))] = cases
    return runs


def verify(total, directory):
    expected = collect()
    runs = read_junit(directory)
    ran = collections.Counter(test_id for cases in runs.values() for test_id, _ in cases)

    for name, cases in runs.items():
        counts = collections.Counter(outcome for _, outcome in cases)
        print(f'{name}: {len(cases)} tests -- {counts["passed"]} passed, '
              f'{counts["failed"]} failed, {counts["skipped"]} skipped')
    # Every failing test by ID, so one run can be compared with another.
    failed = sorted(test_id for cases in runs.values() for test_id, outcome in cases if outcome == 'failed')
    for test_id in failed:
        print(f'FAILED {test_id}')

    missing = sorted(set(expected) - set(ran))
    unexpected = sorted(set(ran) - set(expected))
    repeated = sorted(test_id for test_id, n in ran.items() if n > 1)
    print(f'collected {len(expected)} tests in {len(file_counts(expected))} files; '
          f'{sum(ran.values())} results from {len(runs)} of {total} shards')
    for label, ids in (('did not run', missing), ('ran but not collected', unexpected),
                       ('ran more than once', repeated)):
        if ids:
            print(f'{len(ids)} {label}:')
            for test_id in ids[:50]:
                print(f'  {test_id}')
    if len(runs) != total or missing or unexpected or repeated:
        raise SystemExit(1)
    print('Every collected E2E test ran exactly once.')


def main(argv):
    if len(argv) == 4 and argv[1] == 'files':
        shard, total = int(argv[2]), int(argv[3])
        if not 1 <= shard <= total:
            raise SystemExit(f'shard must be between 1 and {total}')
        ids = collect()
        owner = assign(file_counts(ids), total)
        files = sorted(path for path, index in owner.items() if index == shard)
        sys.stderr.write(f'Shard {shard}/{total}: {len(files)} files, '
                         f'{sum(file_counts(ids)[path] for path in files)} of {len(ids)} tests\n')
        print('\n'.join(files))
    elif len(argv) == 4 and argv[1] == 'verify':
        verify(int(argv[2]), argv[3])
    else:
        raise SystemExit(__doc__)


if __name__ == '__main__':
    main(sys.argv)
