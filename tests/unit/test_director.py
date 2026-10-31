from __future__ import annotations

from pathlib import Path

import pytest

from unbidden.contracts.common import EvidenceLevel, EvidenceRef
from unbidden.contracts.guardian import Mandate
from unbidden.contracts.opportunity import ActionKind, Opportunity, OpportunityStatus
from unbidden.director.decide import Context, decide

pytestmark = pytest.mark.unit


def opp(
    category: str = "types", level: int = 1, improved: bool | None = None, tests: str = "passed", **kw: object
) -> Opportunity:
    details: dict[str, object] = {}
    if improved is not None:
        details["verdict"] = {"improved": improved, "evidence_level": level, "tests": tests}
    return Opportunity(
        source="tsc", category=category, title="t", summary="s", dedup_key="k",
        evidence=[EvidenceRef(kind="file", locator="a")], evidence_level=EvidenceLevel(level), details=details,
        **kw,  # type: ignore[arg-type]
    )  # fmt: skip


def test_new_opportunity_runs_an_experiment(mandate: Mandate) -> None:
    assert decide(opp(), mandate, Context(0, 0)).chosen is ActionKind.RUN_EXPERIMENT


def test_unknown_category_is_declined_with_reason(mandate: Mandate) -> None:
    decision = decide(opp(category="vibes"), mandate, Context(0, 0))
    assert decision.chosen is ActionKind.DECLINE and "vibes" in decision.reason


def test_proven_l4_is_proposed_unless_the_cap_is_full(mandate: Mandate) -> None:
    proven = opp(level=4, improved=True, status=OpportunityStatus.EXPERIMENTING)
    assert decide(proven, mandate, Context(0, 0)).chosen is ActionKind.PROPOSE_CHANGE
    capped = decide(proven, mandate, Context(3, 0))
    assert capped.chosen is ActionKind.WAIT and "cap 3" in capped.reason


@pytest.mark.parametrize("tests", ["regression", "flakier", "not_run", "infra_failure", "inconclusive", None])
def test_an_improvement_the_suite_did_not_validate_is_never_proposed(tests: str | None, mandate: Mandate) -> None:
    # A5: even under a mandate that would accept a lab improvement (L3), and even when the opportunity once reached L4.
    mandate.evaluation.minimum_evidence_for_proposal = 3
    proven = opp(level=4, improved=True, tests=tests, status=OpportunityStatus.EXPERIMENTING)  # type: ignore[arg-type]
    decision = decide(proven, mandate, Context(0, 0))
    assert decision.chosen is ActionKind.DECLINE and "did not validate" in decision.reason


def test_the_level_proposed_is_the_experiments_not_the_highest_ever(mandate: Mandate) -> None:
    proven = opp(level=4, improved=True, status=OpportunityStatus.EXPERIMENTING)
    proven.details["verdict"]["evidence_level"] = 3  # type: ignore[index]
    assert decide(proven, mandate, Context(0, 0)).chosen is ActionKind.DECLINE


def test_l3_is_not_enough_for_the_default_mandate(mandate: Mandate) -> None:
    decision = decide(opp(level=3, improved=True), mandate, Context(0, 0))
    assert decision.chosen is ActionKind.DECLINE and "L4" in decision.reason


def test_gives_up_after_repeated_failures(mandate: Mandate) -> None:
    assert decide(opp(level=2), mandate, Context(0, 2)).chosen is ActionKind.DECLINE


def test_style_findings_outside_the_ci_scope_are_declined(mandate: Mandate) -> None:
    lint = opp(category="lint")
    lint.details = {"paths": ["scripts/release.py"]}
    decision = decide(lint, mandate, Context(0, 0, checked_dirs=("backend",)))
    assert decision.chosen is ActionKind.DECLINE and "backend" in decision.reason
    lint.details = {"paths": ["backend/app/main.py"]}
    assert decide(lint, mandate, Context(0, 0, checked_dirs=("backend",))).chosen is ActionKind.RUN_EXPERIMENT
    bug = opp(category="bugs")
    bug.details = {"paths": ["scripts/release.py"]}
    assert decide(bug, mandate, Context(0, 0, checked_dirs=("backend",))).chosen is ActionKind.RUN_EXPERIMENT


def test_style_from_a_tool_the_ci_does_not_run_is_declined_and_waits_when_the_ci_is_unknown(mandate: Mandate) -> None:
    opp = Opportunity(
        source="ruff-baseline",
        category="lint",
        title="t",
        summary="s",
        dedup_key="k",
        evidence=[EvidenceRef(kind="file", locator="x")],
        details={"tool": "ruff-baseline", "paths": ["rich/cells.py"]},
    )
    declined = decide(opp, mandate, Context(open_pull_requests=0, attempts=0, ci_commands="make typecheck\npytest"))
    assert declined.chosen is ActionKind.DECLINE and "does not run ruff" in declined.reason
    waiting = decide(opp, mandate, Context(open_pull_requests=0, attempts=0, ci_commands=None))
    assert waiting.chosen is ActionKind.WAIT
    acted = decide(opp, mandate, Context(open_pull_requests=0, attempts=0, ci_commands="uv run ruff check ."))
    assert acted.chosen is not ActionKind.DECLINE


def test_style_findings_against_a_green_ci_of_the_same_tool_are_unbiddens_environment(mandate: Mandate) -> None:
    opp = Opportunity(
        source="eslint",
        category="lint",
        title="t",
        summary="s",
        dedup_key="k",
        evidence=[EvidenceRef(kind="file", locator="x")],
        details={"tool": "eslint", "paths": ["app/x.js"]},
    )
    green = Context(open_pull_requests=0, attempts=0, ci_commands="pnpm run eslint", ci_status="green")
    decided = decide(opp, mandate, green)
    assert decided.chosen is ActionKind.DECLINE and "environment" in decided.reason
    red = Context(open_pull_requests=0, attempts=0, ci_commands="pnpm run eslint", ci_status="red")
    assert decide(opp, mandate, red).chosen is not ActionKind.DECLINE


def test_type_errors_a_green_job_of_the_same_tool_does_not_report_are_unbiddens_environment(mandate: Mandate) -> None:
    # marshmallow, pilot method check: mypy in the sandbox called two `type: ignore` unused; the team's mypy job was
    # green on that commit, so they were needed there. Removing them passed the lab and would have broken their CI.
    found = Opportunity(
        source="mypy",
        category="types",
        title="2 mypy errors in tests/test_fields.py",
        summary="unused-ignore",
        dedup_key="mypy:tests/test_fields.py",
        evidence=[EvidenceRef(kind="file", locator="tests/test_fields.py")],
        details={"tool": "mypy", "paths": ["tests/test_fields.py"]},
    )
    # As ci_commands reads it: the workflow's step, then the tox environment it names.
    commands = "uv run tox -e mypy\n[testenv:mypy]\ncommands = mypy --show-error-codes"
    ctx = Context(open_pull_requests=0, attempts=0, ci_commands=commands, tool_status={"mypy": "green"})
    decided = decide(found, mandate, ctx)
    assert decided.chosen is ActionKind.DECLINE and "environment" in decided.reason
    red = Context(open_pull_requests=0, attempts=0, ci_commands=commands, tool_status={"mypy": "red"})
    assert decide(found, mandate, red).chosen is ActionKind.RUN_EXPERIMENT


def test_a_lab_that_could_not_run_waits_instead_of_counting_as_a_failed_experiment(mandate: Mandate) -> None:
    blocked = opp(category="performance")
    blocked.details = {"rev": "abc", "blocked": {"rev": "abc", "why": "cannot measure: no a single Alembic head"}}
    decision = decide(blocked, mandate, Context(0, 0))
    assert decision.chosen is ActionKind.WAIT and "Alembic" in decision.reason
    blocked.details = {**blocked.details, "rev": "def"}  # a new commit: worth trying again
    assert decide(blocked, mandate, Context(0, 0)).chosen is ActionKind.RUN_EXPERIMENT


def test_a_reopened_opportunity_keeps_its_history_and_gets_new_experiment_keys(tmp_path: Path) -> None:
    from unbidden.director.decide import reopen
    from unbidden.store import Store

    store = Store(tmp_path / "s.db")
    o = opp(category="performance")
    o.details = {"rev": "abc", "attempts": 2, "decision": {"chosen": "decline"}}
    o.status = OpportunityStatus.DECLINED
    store.put("opportunities", o)
    again = reopen(store, o, "the lab could not run fixtures (fixed)")
    assert again.status is OpportunityStatus.OPEN and again.details == {
        "rev": "abc",
        "reopened": 1,
        "attempts_total": 2,
    }  # the attempts made are kept as a total
    events = [e for e in store.events() if e.entity_id == o.id]
    assert events[-1].payload == {"reopened": 1, "reason": "the lab could not run fixtures (fixed)"}


def test_a_forks_shared_commits_are_judged_by_the_parents_ci(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import unbidden.observe.ci as ci

    green = [{"name": "test", "status": "completed", "conclusion": "success"}]
    monkeypatch.setattr(
        ci, "fetch_runs", lambda slug, rev, token=None: (green, None) if slug == "upstream/lib" else ([], None)
    )  # pyright: ignore[reportUnknownLambdaType]
    monkeypatch.setattr(ci, "fork_parent", lambda slug, token=None: "upstream/lib" if slug == "me/lib" else None)  # pyright: ignore[reportUnknownLambdaType]
    assert ci.ci_verdicts(tmp_path, "abc", "me/lib", None, set()) == ("green", {}, None)
    assert ci.ci_verdicts(tmp_path, "abc", "other/lib", None, set()) == (None, {}, None)


def test_an_unreadable_ci_is_not_no_checks_and_the_director_waits_on_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mandate: Mandate
) -> None:
    import unbidden.observe.ci as ci

    why = "GitHub answered 403 for acme/lib@abc (rate limit exhausted, no token was used)"
    monkeypatch.setattr(ci, "fetch_runs", lambda *a, **k: (None, why))  # pyright: ignore[reportUnknownLambdaType]
    assert ci.ci_verdicts(tmp_path, "abc", "acme/lib", None, set()) == (ci.UNREADABLE, {}, why)
    found = Opportunity(
        source="tsc", category="types", title="t", summary="s", dedup_key="k",
        evidence=[EvidenceRef(kind="file", locator="a.ts")], details={"tool": "tsc", "paths": ["a.ts"]},
    )  # fmt: skip
    commands = "pnpm check\ntsc -b tsconfig.json"  # the step, then the package script it calls
    ctx = Context(open_pull_requests=0, attempts=0, ci_commands=commands, ci_status=ci.UNREADABLE, ci_problem=why)
    decided = decide(found, mandate, ctx)
    assert (
        decided.chosen is ActionKind.WAIT and "could not be read" in decided.reason and "rate limit" in decided.reason
    )


def test_the_cis_python_versions_are_read_from_workflows_tox_and_nox(tmp_path: Path) -> None:
    import subprocess

    from unbidden.observe.ci import ci_python_versions

    workflow = "\n".join(
        [
            "jobs:",
            "  t:",
            "    strategy:",
            "      matrix:",
            '        python-version: ["3.11", "3.13"]',
            "    steps:",
            "      - uses: actions/setup-python@v5",
            "        with:",
            "          python-version: ${{ matrix.python-version }}",
        ]
    )
    files = {".github/workflows/t.yml": workflow, "tox.ini": "[tox]\nenvlist = lint,mypy,py{310,312},py3{13-14}\n"}
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for path, text in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    assert ci_python_versions(tmp_path, "HEAD") == ["3.10", "3.11", "3.12", "3.13", "3.14"]


def test_a_tool_the_ci_runs_through_tox_and_a_matrix_counts_as_run(tmp_path: Path) -> None:
    import subprocess

    from unbidden.observe.ci import ci_commands

    workflow = "\n".join(
        [
            "jobs:",
            "  tests:",
            "    strategy:",
            "      matrix:",
            "        include:",
            "          - { name: mypy, tox: mypy }",
            "    steps:",
            "      - run: uv run tox -e ${{ matrix.tox }}",
        ]
    )
    files = {".github/workflows/b.yml": workflow, "tox.ini": "[testenv:mypy]\ncommands = mypy --show-error-codes\n"}
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for path, text in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    commands = ci_commands(tmp_path, "HEAD")
    assert commands is not None and "mypy --show-error-codes" in commands


def test_a_run_that_said_nothing_is_not_green() -> None:
    from unbidden.observe.ci import run_state, verdict_of

    def runs(*pairs: tuple[str, str | None]) -> list[str]:
        return [run_state({"status": s, "conclusion": c}) for s, c in pairs]

    done = ("completed", "success")
    # B1: cancelled, neutral, stale and missing conclusions used to count as green.
    for conclusion in ("cancelled", "neutral", "stale", None):
        assert verdict_of(runs(done, ("completed", conclusion))) == "unknown"
    assert verdict_of(runs(done, ("completed", "skipped"))) == "green"
    assert verdict_of(runs(("completed", "skipped"))) == "unknown"  # nothing ran
    assert verdict_of(runs(done, ("completed", "startup_failure"))) == "red"
    # B2: a picture with runs still going is pending, not the verdict of the runs that finished.
    assert verdict_of(runs(done, ("in_progress", None))) == "pending"
    assert verdict_of([]) is None


def test_findings_of_a_tool_whose_ci_jobs_are_still_running_wait(mandate: Mandate) -> None:
    found = opp(category="types")
    found.details = {**found.details, "tool": "mypy", "paths": ["a.py"]}
    ctx = Context(open_pull_requests=0, attempts=0, ci_commands="mypy .", tool_status={"mypy": "pending"})
    decided = decide(found, mandate, ctx)
    assert decided.chosen is ActionKind.WAIT and "still running" in decided.reason


def test_check_runs_are_read_across_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    import httpx

    import unbidden.observe.ci as stubbed

    ci = importlib.reload(stubbed)  # the real reader, not the network stub every unit test gets
    pages = {
        "1": [{"name": f"job{i}", "status": "completed", "conclusion": "success"} for i in range(100)],
        "2": [{"name": "slow", "status": "in_progress", "conclusion": None}],
    }

    class Response:
        status_code = 200

        def __init__(self, page: str) -> None:
            self.page, self.headers = page, {}

        def json(self) -> dict[str, object]:
            return {"total_count": 101, "check_runs": pages[self.page]}

    monkeypatch.setattr(httpx, "get", lambda url, params, headers, timeout: Response(params["page"]))  # pyright: ignore[reportUnknownLambdaType]
    runs, problem = ci.fetch_runs("acme/lib", "abc")
    assert problem is None and runs is not None and len(runs) == 101
    # The 101st run, on the second page, is still running: the commit is not green yet.
    assert ci.verdict_of([ci.run_state(r) for r in runs]) == "pending"


def test_the_cycle_reuses_only_a_finished_ci_verdict(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mandate: Mandate
) -> None:
    from types import SimpleNamespace

    import unbidden.observe.ci as ci
    from unbidden.daemon.cycle import Cycle
    from unbidden.store import Store

    answers = iter([("pending", {}, None), (None, {}, None), ("green", {}, None), ("red", {}, None)])
    asked: list[str | None] = []

    def verdicts(*_: object) -> tuple[str | None, dict[str, str], str | None]:
        answer = next(answers)
        asked.append(answer[0])
        return answer

    monkeypatch.setattr(ci, "ci_verdicts", verdicts)
    cycle = Cycle(runtime=SimpleNamespace(workspace=SimpleNamespace(repo=tmp_path), store=Store(None)))  # type: ignore[arg-type]
    seen = [cycle._ci_verdicts("abc", mandate)[0] for _ in range(4)]  # pyright: ignore[reportPrivateUsage]
    # A running CI is asked again at the next sweep; "no checks" is then kept for a while instead of asked every sweep.
    assert asked == ["pending", None] and seen == ["pending", None, None, None]


def test_a_finished_verdict_is_reused_until_it_expires(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mandate: Mandate
) -> None:
    import time
    from types import SimpleNamespace

    import unbidden.daemon.cycle as cycle_module
    import unbidden.observe.ci as ci
    from unbidden.store import Store

    answers = iter([("green", {}, None), ("red", {}, None)])
    monkeypatch.setattr(ci, "ci_verdicts", lambda *_: next(answers))  # pyright: ignore[reportUnknownLambdaType]
    cycle = cycle_module.Cycle(runtime=SimpleNamespace(workspace=SimpleNamespace(repo=tmp_path), store=Store(None)))  # type: ignore[arg-type]
    assert cycle._ci_verdicts("abc", mandate)[0] == "green"  # pyright: ignore[reportPrivateUsage]
    assert cycle._ci_verdicts("abc", mandate)[0] == "green"  # pyright: ignore[reportPrivateUsage]
    now = time.monotonic()
    monkeypatch.setattr(cycle_module.time, "monotonic", lambda: now + cycle_module.CI_TTL_S["green"] + 1)
    assert cycle._ci_verdicts("abc", mandate)[0] == "red"  # pyright: ignore[reportPrivateUsage]  # a re-run changed it


def test_type_errors_outside_what_the_ci_checks_with_that_tool_are_declined(mandate: Mandate) -> None:
    # Prefect, stage 10: its CI runs `pyright -p pyrightconfig-ci.json`, which includes only src/; Unbidden's own
    # pyright fixed errors in benches/ and reached L4 on code the team never holds to that standard.
    def found(path: str) -> Opportunity:
        return Opportunity(
            source="pyright", category="types", title=f"pyright errors in {path}", summary="s",
            dedup_key=f"pyright:{path}", evidence=[EvidenceRef(kind="file", locator=path)],
            details={"tool": "pyright", "paths": [path]},
        )  # fmt: skip

    ctx = Context(open_pull_requests=0, attempts=0, ci_commands="pyright -p c.json", tool_scopes={"pyright": ("src",)})
    outside = decide(found("benches/bench_flows.py"), mandate, ctx)
    assert outside.chosen is ActionKind.DECLINE and "only in src" in outside.reason
    assert decide(found("src/prefect/flows.py"), mandate, ctx).chosen is not ActionKind.DECLINE


def test_a_tools_ci_scope_is_its_named_paths_or_its_configs_include_and_never_words_in_a_sentence() -> None:
    from unbidden.observe.ci import tool_scope

    tracked = ["src/pkg/a.py", "benches/b.py", "docs/x.md", "pyrightconfig-ci.json"]
    configs = {"pyrightconfig-ci.json": '{\n  // only the package\n  "include": ["src/"]\n}'}
    commands = (
        "uv run pyright -p pyrightconfig-ci.json --level error --outputjson\n"
        "uv run pyright --ignoreexternal --verifytypes prefect\n"
        'echo "pyright exits non-zero when no files match its configuration"'
    )
    assert tool_scope(configs.get, tracked, commands, "pyright") == ("src",)
    assert tool_scope(configs.get, tracked, "mypy src/pkg benches", "mypy") == ("benches", "src/pkg")
    assert tool_scope(configs.get, tracked, "mypy .", "mypy") is None  # the whole tree
    assert tool_scope(configs.get, tracked, "pytest", "pyright") is None  # not run at all
