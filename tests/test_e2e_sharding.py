"""The browser suite's CI shards (tests/e2e/shard.py): whole files, each on
exactly one shard, the same split every time."""

import importlib.util
import random
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location(
    'e2e_shard', Path(__file__).resolve().parent / 'e2e' / 'shard.py'
)
shard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(shard)

FILES = {f'tests/e2e/test_{index:03d}.py': (index * 7) % 23 + 1 for index in range(127)}


def test_every_file_is_on_exactly_one_shard():
    owner = shard.assign(FILES, 4)
    assert set(owner) == set(FILES)                       # every file, nothing extra
    assert set(owner.values()) == {1, 2, 3, 4}
    files_per_shard = [[path for path, index in owner.items() if index == n] for n in (1, 2, 3, 4)]
    listed = [path for files in files_per_shard for path in files]
    assert sorted(listed) == sorted(FILES)                # no file twice, none lost
    assert len(listed) == len(set(listed))


def test_the_split_is_deterministic_whatever_the_collection_order():
    first = shard.assign(FILES, 4)
    items = list(FILES.items())
    for seed in range(5):
        random.Random(seed).shuffle(items)
        assert shard.assign(dict(items), 4) == first


def test_shards_are_balanced_by_test_count():
    owner = shard.assign(FILES, 4)
    loads = [sum(count for path, count in FILES.items() if owner[path] == n) for n in (1, 2, 3, 4)]
    assert max(loads) - min(loads) <= max(FILES.values())


def test_one_shard_takes_everything_and_zero_shards_is_an_error():
    assert set(shard.assign(FILES, 1).values()) == {1}
    with pytest.raises(ValueError):
        shard.assign(FILES, 0)


def test_collection_output_is_read_as_test_ids():
    output = (
        'tests/e2e/test_a.py::test_one[chromium]\n'
        'tests/e2e/test_a.py::test_two[chromium-phone]\n'
        'tests/e2e/test_b.py::test_three[chromium]\n'
        '\n'
        '3 tests collected in 0.42s\n'
    )
    ids = shard.parse_collection(output)
    assert ids == [
        'tests/e2e/test_a.py::test_one[chromium]',
        'tests/e2e/test_a.py::test_two[chromium-phone]',
        'tests/e2e/test_b.py::test_three[chromium]',
    ]
    assert shard.file_counts(ids) == {'tests/e2e/test_a.py': 2, 'tests/e2e/test_b.py': 1}


def test_junit_results_map_back_to_the_collected_ids():
    assert shard.junit_id('tests.e2e.test_live_move_single_writer', 'test_x[chromium]') == (
        'tests/e2e/test_live_move_single_writer.py::test_x[chromium]'
    )
