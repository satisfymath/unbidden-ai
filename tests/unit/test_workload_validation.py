"""Stage 10: a workload is checked before it is trusted (docs/bench/stage10-diagnosis.md).

Statically: Spoolman's workloads asked for fixtures of another test directory and took `*args`, which pytest reads as
fixtures. At the base: the engine must show the claimed operation, on enough data, with a result to compare. Between
sides: the same responses, or the candidate is wrong, however fast."""

from __future__ import annotations

from pathlib import Path

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


def test_test_packages_are_never_the_product_a_probe_targets() -> None:
    """Stage 10 v2 regression, Spoolman: `tests_integration` was probed and a fix to its conftest's helper promoted."""
    from unbidden.research.robustness import not_product

    assert all(not_product(n) for n in ("tests", "tests_integration", "integration_tests", "testing", "test_utils"))
    assert not any(not_product(n) for n in ("spoolman", "attestation", "contest", "latest"))


@pytest.mark.parametrize(
    ("query", "table", "column", "reads"),
    [
        ("SELECT * FROM spool WHERE spool.filament_id = $1", "spool", "filament_id", True),
        ("SELECT * FROM filament LEFT OUTER JOIN vendor ON vendor.id = filament.vendor_id WHERE filament.id = $1",
         "filament", "vendor_id", False),  # vendor looked up by its key: an index on filament.vendor_id does not serve
        ("SELECT * FROM vendor JOIN filament ON filament.vendor_id = vendor.id WHERE vendor.id = $1",
         "filament", "vendor_id", True),
        ("SELECT c.* FROM commentaries c WHERE c.article_id = $1", "commentaries", "article_id", True),
        ('SELECT 1 FROM ONLY "public"."favorites" x WHERE "article_id" OPERATOR(pg_catalog.=) $1 FOR KEY SHARE OF x',
         "favorites", "article_id", True),  # PostgreSQL's own foreign-key check on a parent's delete
        ("SELECT * FROM comments WHERE comments.id = $1", "comments", "article_id", False),
    ],
)  # fmt: skip
def test_the_engine_statement_says_whether_the_table_is_looked_up_by_the_column(
    query: str, table: str, column: str, reads: bool
) -> None:
    from unbidden.lab.seed import reads_by

    assert reads_by(query, table, column) is reads


def test_fixtures_a_conftest_star_imports_through_a_package_are_visible(tmp_path: Path) -> None:
    # mealie, stage 10: conftest.py does `from tests.fixtures import *`, whose __init__.py re-exports its modules with
    # `from .fixture_users import *`; `unique_user` was taken as invisible and every workload was refused.
    import subprocess

    from unbidden.lab.perf import PerfLab

    files = {
        "tests/conftest.py": "from tests.fixtures import *  # noqa\n",
        "tests/fixtures/__init__.py": "from .fixture_users import *\n",
        "tests/fixtures/fixture_users.py": "import pytest\n\n@pytest.fixture\ndef unique_user():\n    pass\n",
        "tests/data/x.py": "@pytest.fixture\ndef not_loaded():\n    pass\n",
    }
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"], cwd=tmp_path, check=True)
    lab = PerfLab.__new__(PerfLab)
    lab.repo = tmp_path
    lab._show = lambda rev, p: (tmp_path / p).read_text()  # type: ignore[method-assign]
    visible = PerfLab._visible_fixtures(lab, "HEAD", "tests/unit")  # pyright: ignore[reportPrivateUsage]
    assert "unique_user" in visible and "not_loaded" not in visible


def test_generated_ids_and_times_do_not_make_two_sessions_with_the_same_data_differ() -> None:
    # fst, stage 10: every base session answered with other uuid4 ids and creation times, so the base never agreed
    # with itself and a 72% faster index stayed inconclusive. Values of that shape compare as "generated"; anything
    # else still counts.
    import json

    from unbidden.lab import perf

    start = perf.DRIVER.index("def _digest(r):")
    namespace: dict[str, object] = {}
    exec("import json\n" + perf.DRIVER[start : perf.DRIVER.index("\n\n\n", start)], namespace)
    digest = namespace["_digest"]

    class Response:
        def __init__(self, value: object) -> None:
            self.content = json.dumps(value).encode()

    def of(ident: str, at: str, n: int) -> str:
        return digest(Response([{"id": ident, "created_at": at, "n": n}]))[0]  # type: ignore[operator]

    one = of("0e7be872-1111-4222-8333-444455556666", "2026-10-31T05:00:01.123456", 1)
    assert one == of("9a1be872-1111-4222-8333-444455556666", "2026-10-30T01:02:03Z", 1)
    assert one != of("9a1be872-1111-4222-8333-444455556666", "2026-10-30T01:02:03Z", 2)
