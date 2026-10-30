"""Stage 10: a workload is checked before it is trusted (docs/bench/stage10-diagnosis.md).

Statically: Spoolman's workloads asked for fixtures of another test directory and took `*args`, which pytest reads as
fixtures. At the base: the engine must show the claimed operation, on enough data, with a result to compare. Between
sides: the same responses, or the candidate is wrong, however fast."""

from __future__ import annotations

import pytest

from unbidden.lab.perf import BUILTIN_FIXTURES, SAMPLES, SEED_ROWS, _same, signature_problems, validate_in_process

pytestmark = pytest.mark.unit
VISIBLE = {"client", "session", *BUILTIN_FIXTURES}


@pytest.mark.parametrize(
    ("source", "why"),
    [
        ("def build(*a, **k):\n    pass\n", "*args"),
        ("def build(random_filament):\n    pass\n", "random_filament"),
        ("def make(client):\n    pass\n", "no top-level `build`"),
        ("def build(client:\n", "not valid Python"),
    ],
)
def test_a_signature_pytest_cannot_satisfy_is_refused_before_running(source: str, why: str) -> None:
    assert why in signature_problems(source, VISIBLE)


def test_a_signature_of_visible_fixtures_passes() -> None:
    assert signature_problems("async def build(client, session, request):\n    pass\n", VISIBLE) == ""


def record(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "samples_ms": [1.0] * SAMPLES,
        "statements": [{"calls": SAMPLES + 3, "mean_ms": 2.0, "query": "SELECT * FROM comments WHERE article_id = $1"}],
        "inserted": {"comments": SEED_ROWS},
        "digests": ["d"] * SAMPLES,
        "sample": '[{"id": 1}]',
    }
    return {**base, **over}


def test_a_workload_that_does_the_claimed_operation_on_its_data_is_valid() -> None:
    ok, problems, passed = validate_in_process(record(), ("comments", "article_id"), reads=True)
    assert ok and not problems and any("on every call" in p for p in passed)


@pytest.mark.parametrize(
    ("over", "why"),
    [
        ({"statements": [{"calls": 23, "mean_ms": 1.0, "query": "SELECT * FROM comments WHERE id = $1"}]},
         "did not run a statement that reads comments by article_id"),  # the workload does not use the column
        ({"inserted": {"comments": 50}}, "only 50 rows"),
        ({"digests": [None] * SAMPLES}, "status code only"),
        ({"sample": "[]"}, "returned no data"),
    ],
)  # fmt: skip
def test_a_workload_that_does_not_measure_what_it_claims_is_not_valid(over: dict[str, object], why: str) -> None:
    ok, problems, _ = validate_in_process(record(**over), ("comments", "article_id"), reads=True)
    assert not ok and any(why in p for p in problems)


def test_the_same_responses_on_both_sides_or_a_named_difference() -> None:
    same = [{"arm": a, "digests": ["x", "y"]} for a in ("base", "candidate", "base", "candidate")]
    assert _same(same)[0] is True
    wrong = [{"arm": "base", "digests": ["x", "y"]}, {"arm": "candidate", "digests": ["x", "z"]}]
    ok, note = _same(wrong)
    assert ok is False and "1 of 2 responses differ" in note
    assert _same([{"arm": "base", "digests": []}, {"arm": "candidate", "digests": ["x"]}])[0] is None


def test_a_written_migration_follows_the_projects_own_conventions() -> None:
    """Stage 10, Spoolman: its migrations are linted with every rule; the index's migration must look like them."""
    from unbidden.lab.perf import _INDEX_MIGRATION, in_house_style

    head = ('"""tags.\n\nRevision ID: fe49\n"""\n\nrevision: str = "fe49"\ndown_revision: str | None = "9c1d"\n\n\n'
            'def upgrade() -> None:\n    """Create the tag table."""\n    pass\n')  # fmt: skip
    written = in_house_style(_INDEX_MIGRATION.format(table="t", column="c", revision="r1", head_rev="fe49", name="ix"),
                             head)  # fmt: skip
    assert written.startswith('"""add index on t.c.\n')
    assert 'revision: str = "r1"' in written and 'down_revision: str | None = "fe49"' in written
    assert 'def upgrade() -> None:\n    """Add the index."""' in written
    plain = in_house_style(_INDEX_MIGRATION.format(table="t", column="c", revision="r1", head_rev="h", name="ix"),
                           '"""x\n"""\nrevision = "h"\n\ndef upgrade():\n    pass\n')  # fmt: skip
    assert "def upgrade():" in plain and "-> None" not in plain  # an older project's style is kept as it is
