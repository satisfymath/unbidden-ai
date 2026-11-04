"""The campaign 13 harness at scale (0.18.0): copies keep the team's checks and drop only what publishes; parallel
workers never lose a summary line nor share a port; the final runner's order and resume; the joined report row from
records only; the export step when the installed product lacks the command."""

from __future__ import annotations

import json
import multiprocessing
import queue
from pathlib import Path
from typing import Any

import pytest

from bench.campaign13 import run_final
from bench.campaign13.common import Record, Step, update_summary
from bench.campaign13.copies import COPY_PREFIX, apply_plan, copy_slug, workflow_files
from bench.campaign13.level_b import (
    CUSTOM_AUTONOMY,
    command_missing,
    deploy_target,
    export_workspace,
    keep_archive,
    summarize_store,
)
from bench.campaign13.report import comparison, joined_row, joined_rows, joined_table
from bench.campaign13.workflows import plan_workflows, remove_jobs

pytestmark = pytest.mark.unit

TESTS = """name: tests
on:
  pull_request:
  push:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install -e .[test]
      - name: Run tests
        run: pytest -q
      - uses: codecov/codecov-action@v4
"""

RELEASE = """name: release
on:
  release:
    types: [published]
jobs:
  pypi:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: python -m build
      - uses: pypa/gh-action-pypi-publish@release/v1
"""

BOT = """on:
  issues:
    types: [opened]
jobs:
  manage:
    runs-on: ubuntu-latest
    steps:
      - uses: tiangolo/issue-manager@0.5.0
"""

CI = """name: ci
on: [push, pull_request]
jobs:
  style:
    runs-on: ubuntu-latest
    steps:
      - run: ruff check .
  build-image:
    runs-on: ubuntu-latest
    steps:
      - uses: docker/build-push-action@v6
        with:
          push: false
          tags: app:test
  test:
    needs: [style, build-image]
    runs-on: ubuntu-latest
    steps:
      - name: Run tests
        run: pytest
  # publishes the images on a push to the default branch
  publish-images:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: docker/login-action@v3
      - uses: docker/build-push-action@v6
        with:
          push: true
  publish-release:
    needs: publish-images
    runs-on: ubuntu-latest
    steps:
      - run: gh release create v1
"""

DEPLOY_NEEDED = """on: pull_request
jobs:
  deploy-preview:
    runs-on: ubuntu-latest
    steps:
      - run: echo build
  smoke:
    needs: deploy-preview
    runs-on: ubuntu-latest
    steps:
      - name: Run tests
        run: pytest tests/smoke
"""


def test_copy_keeps_the_teams_checks_and_drops_only_what_publishes(tmp_path: Path) -> None:
    files = {"tests.yml": TESTS, "release.yml": RELEASE, "issue-manager.yml": BOT, "ci.yml": CI,
             "preview.yml": DEPLOY_NEEDED}  # fmt: skip
    plans = {p.file: p for p in plan_workflows(files)}
    assert plans["tests.yml"].action == "keep"  # a coverage upload inside a test job does not remove the job
    assert plans["release.yml"].action == "remove"
    assert plans["issue-manager.yml"].action == "remove"  # a bot: triggered by issues, checks no code
    assert plans["ci.yml"].action == "edit"
    assert plans["ci.yml"].removed_jobs == ["publish-images", "publish-release"]
    assert plans["ci.yml"].kept_jobs == ["style", "build-image", "test"]  # an image built without a push is a check
    assert plans["preview.yml"].action == "keep"  # a deploy-named job a test job needs stays
    cut = remove_jobs(CI, plans["ci.yml"].removed_jobs)
    assert "publish-images" not in cut and "gh release" not in cut and "docker/login-action" not in cut
    assert cut == CI[: CI.index("  # publishes the images")]  # the kept jobs byte for byte
    # applied to a checkout
    folder = tmp_path / ".github" / "workflows"
    folder.mkdir(parents=True)
    for name, text in files.items():
        (folder / name).write_text(text)
    removed, edited = apply_plan(tmp_path, list(plans.values()))
    assert sorted(removed) == ["issue-manager.yml", "release.yml"]
    assert [e["file"] for e in edited] == [".github/workflows/ci.yml"]
    assert sorted(workflow_files(tmp_path)) == ["ci.yml", "preview.yml", "tests.yml"]
    assert (folder / "tests.yml").read_text() == TESTS
    assert COPY_PREFIX == "c13-" and copy_slug("fst") == "satisfymath/c13-fst"


def test_remove_jobs_follows_the_files_own_indentation() -> None:
    text = "on: push\njobs:\n    a:\n        runs-on: x\n    b:\n        runs-on: y\nenv:\n    K: v\n"
    assert remove_jobs(text, ["a"]) == "on: push\njobs:\n    b:\n        runs-on: y\nenv:\n    K: v\n"


def _writer(path: str, worker: int, count: int) -> None:
    for i in range(count):
        update_summary(Path(path), {"name": f"w{worker}-{i}", "run": "B1"}, keys=("name", "run"))


def test_two_concurrent_summary_writers_never_lose_a_line(tmp_path: Path) -> None:
    path = tmp_path / "summary-B.json"
    ctx = multiprocessing.get_context("fork")
    procs = [ctx.Process(target=_writer, args=(str(path), w, 40)) for w in range(2)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=60)
        assert p.exitcode == 0
    names = {s["name"] for s in json.loads(path.read_text())}
    assert names == {f"w{w}-{i}" for w in range(2) for i in range(40)}
    update_summary(path, {"name": "w0-0", "run": "B1", "again": True}, keys=("name", "run"))  # replaced, not doubled
    rows = json.loads(path.read_text())
    assert len(rows) == 80 and [r for r in rows if r["name"] == "w0-0"] == [
        {"name": "w0-0", "run": "B1", "again": True}
    ]


def test_worker_ports_never_overlap() -> None:
    seen: set[int] = set()
    for i in range(32):
        ports = run_final.worker_ports(i)
        values = set(ports.values())
        assert len(values) == len(ports)
        assert all(run_final.BASE_PORT + i * run_final.SPAN <= p < run_final.BASE_PORT + (i + 1) * run_final.SPAN
                   for p in values)  # fmt: skip
        assert not values & seen
        seen |= values
    with pytest.raises(ValueError):
        run_final.worker_ports(-1)


CORPUS: list[dict[str, Any]] = [
    {"name": "fst", "family": "api-postgres", "level_b": True, "lab": "fst", "build": "uv"},
    {"name": "rich", "family": "library", "level_b": True, "build": "hatch"},
    {"name": "misago", "family": "web-django", "level_b": True, "build": "pip"},
    {"name": "pipx", "family": "cli", "level_b": True, "build": "hatch"},
    {"name": "humanize", "family": "library", "level_b": False, "build": "hatch"},
    {"name": "zod", "family": "typescript", "level_b": False, "build": "n/a"},
    {"name": "ctfd", "family": "web-flask", "level_b": False, "build": "pip"},
]


def test_run_final_order_eligibility_and_resume(tmp_path: Path) -> None:
    jobs = run_final.plan(CORPUS, order="libraries-first")
    assert [(j.name, j.level) for j in jobs] == [
        ("rich", "B"), ("pipx", "B"), ("fst", "B"), ("misago", "B"), ("humanize", "A"), ("zod", "A"), ("ctfd", "A"),
    ]  # fmt: skip
    assert len(jobs) == len(CORPUS)  # every repository has a row: Level A where B is not eligible
    every = run_final.plan(CORPUS, all_python=True)
    assert [j.name for j in every if j.level == "B"] == ["fst", "rich", "misago", "pipx", "humanize", "ctfd"]
    assert [j.name for j in every if j.level == "A"] == ["zod"]
    assert [j.name for j in run_final.plan(CORPUS, only={"zod", "fst"})] == ["fst", "zod"]
    # resume: a recorded job is skipped
    (tmp_path / "rich").mkdir()
    (tmp_path / "rich" / "B1.json").write_text("{}")
    (tmp_path / "zod").mkdir()
    (tmp_path / "zod" / "A.json").write_text("{}")
    left = run_final.pending(jobs, tmp_path)
    assert [j.name for j in left] == ["pipx", "fst", "misago", "humanize", "ctfd"]


def test_a_worker_takes_jobs_in_order_on_its_ports_and_survives_a_failure(tmp_path: Path) -> None:
    jobs = run_final.plan(CORPUS, order="libraries-first")
    q: queue.Queue[run_final.Job] = queue.Queue()
    for job in jobs:
        q.put(job)
    seen: list[tuple[str, int]] = []

    def fake(job: run_final.Job, repo: dict[str, Any], ports: dict[str, int], args: dict[str, Any]) -> dict[str, Any]:
        seen.append((job.name, ports["dashboard"]))
        if job.name == "misago":
            raise RuntimeError("copy could not be created")
        path = run_final.record_path(Path(args["out"]), job)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}")
        return {"name": job.name}

    repos = {r["name"]: r for r in CORPUS}
    run_final.worker(3, q, repos, {"out": str(tmp_path)}, runner=fake)
    assert [n for n, _ in seen] == [j.name for j in jobs]
    assert {p for _, p in seen} == {run_final.worker_ports(3)["dashboard"]}
    failures = json.loads((tmp_path / "failures.json").read_text())
    assert [f["name"] for f in failures] == ["misago"]
    assert "worker 3 starts" in (tmp_path / "rich" / "run.log").read_text()
    assert [j.name for j in run_final.pending(jobs, tmp_path)] == ["misago"]


def test_run_final_dry_run_prints_the_plan_and_tool_versions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    corpus = tmp_path / "corpus.yaml"
    corpus.write_text(json.dumps({"candidate": "c", "wheel_sha256": "w", "repos": CORPUS}))  # JSON is YAML
    assert run_final.main([str(corpus), "--out", str(tmp_path / "out"), "--workers", "2", "--dry-run"]) == 0
    head = json.loads(capsys.readouterr().out)
    assert len(head["jobs"]) == 7 and set(head["tools"]) >= {"uv", "gh", "docker", "act"}
    assert not (tmp_path / "out").exists()


def test_deploy_target_and_the_custom_mode() -> None:
    assert deploy_target({"lab": "fst", "family": "api-postgres"}) == "lab"
    assert deploy_target({"family": "web-django"}) == "self_host"
    assert deploy_target({"family": "library"}) == "none"
    assert deploy_target({"family": "cli"}) == "none"
    assert CUSTOM_AUTONOMY["merge_pull_requests"] == "allow" and CUSTOM_AUTONOMY["deploy"] == "deny"


def test_export_unavailable_is_recorded_and_the_run_goes_on(tmp_path: Path) -> None:
    rec = Record(repo="rich", phase="final", run="B1", candidate="c", wheel_sha256="w")

    def missing(name: str, argv: list[str], **_: Any) -> Step:
        return Step(name, argv, 2, 0.1, "", "Error: No such command 'export'.")

    out = export_workspace(tmp_path, {}, tmp_path / "export", rec, runner=missing)
    assert out == {"available": False, "why": "export unavailable", "code": 2}
    assert rec.steps[-1]["name"] == "export"

    def works(name: str, argv: list[str], **_: Any) -> Step:
        dest = Path(argv[argv.index("--out") + 1])
        (dest / "manifest.json").write_text("{}")
        return Step(name, argv, 0, 0.1, '{"ok": true}', "")

    done = export_workspace(tmp_path, {}, tmp_path / "export2", rec, runner=works)
    assert done["available"] and done["ok"] and done["files"] == 1
    assert not command_missing(Step("x", [], 1, 0.1, "", "a real failure"))


def test_archive_is_kept_beside_the_export_unless_too_large(tmp_path: Path) -> None:
    tgz = tmp_path / "rich-B1-final.tgz"
    tgz.write_bytes(b"x" * 2048)
    small = keep_archive(str(tgz), tmp_path / "export")
    assert small["kept"] and (tmp_path / "export" / tgz.name).exists() and len(small["sha256"]) == 64
    big = keep_archive(str(tgz), tmp_path / "export-big", limit=1024)
    assert not big["kept"] and big["bytes"] == 2048 and big["where"] == str(tgz)
    assert not (tmp_path / "export-big" / tgz.name).exists()


LIVE = {"criteria_version": "v2", "alpha": 0.05}


def _b_record() -> dict[str, Any]:
    outcome = {"result": "positive", "deploy": "3:abc123", "criteria": LIVE, "promoted": True}
    opp = {"id": "opp_1", "source": "world", "category": "performance", "evidence_level": 5, "status": "verified",
           "details": {"outcome": outcome}}  # fmt: skip
    lint = {"id": "opp_2", "source": "ruff", "category": "lint", "evidence_level": 1, "status": "open"}
    props = [{"id": "prop_1", "opportunity_id": "opp_1", "experiment_id": "exp_1", "status": "merged",
              "evidence_level": 4, "pr": {"url": "https://github.com/satisfymath/c13-fst/pull/1"}}]  # fmt: skip
    verdicts = [{"experiment_id": "exp_1", "criteria": {"version": "perf-v4"}}]
    counts = summarize_store({"operations.deployed": 2}, {"opportunities": 2, "experiments": 3}, {}, props,
                             [opp, lint], verdicts)  # fmt: skip
    green = [{"status": "completed", "conclusion": "success"}]
    pull = {"number": 1, "head": "unbidden/opp_1", "user": "satisfymath", "created_at": "2026-11-05T10:30:00Z",
            "merged_at": "2026-11-05T11:00:00Z", "checks": green}  # fmt: skip
    return {
        "repo": "fst",
        "run": "B1",
        "started_at": "2026-11-05T07:00:00-0300",
        "facts": {
            "autonomy": {"mode": "autonomous"},
            "checks": {"status": "passed", "collected": 120},
            "cycle1": {"counts": counts},
            "cycle2": {"counts": counts},
            "fork_after_c1": {"pulls": [pull]},
            "fork_after_c2": {"pulls": [pull]},
            "spent_usd": 0.4,
            "asks_answered": [
                {"rule": "lab repository"},
                {"rule": "lab repository"},
                {"rule": "the campaign's model key"},
            ],
            "export": {"available": False, "why": "export unavailable"},
            "setup": {"ok": True},
            "mode_got": "autonomous",
        },
        "steps": [],
        "human": [],
        "blocks": [],
    }


def test_report_joined_row_from_records_only() -> None:
    b = _b_record()
    assert b["facts"]["cycle2"]["counts"]["level_max_criteria"] == LIVE
    verify = [{"slug": "satisfymath/c13-fst", "number": 1, "verdict": "verified"}]
    a = {"repo": "fst", "facts": {"spent_usd": 0, "checks": {"status": "failed", "collected": 9}}, "steps": []}
    row = joined_row("fst", {"class": "dev", "family": "api-postgres"}, a, b, verify)
    assert row["level"] == "L5 (v2; positive after deploy 3:abc123)"
    assert row["checks"] == "passed" and row["collected"] == 120  # the B run's own baseline first
    assert row["opportunities"] == {"lint": 1, "performance": 1}
    assert row["experiments"] == 3 and row["proposals"] == ["L4"]
    assert row["pulls"] == ["#1"] and row["ci"] == ["green"] and row["merged"] == 1 and row["deploys"] == 2
    assert row["verify"] == ["verified"]
    assert row["spent_usd"] == 0.4 and row["cost_per_pr"] == 0.4
    assert row["first_pr_min"] == 30.0  # 10:00Z start, 10:30Z pull request
    assert row["asks"] == 3 and row["ask_rules"] == {"lab repository": 2, "the campaign's model key": 1}
    assert row["export"] == "export unavailable"
    corpus = {"fst": {"class": "dev", "family": "api-postgres"}, "zod": {"class": "frontier", "family": "typescript"}}
    zod_a = {"repo": "zod", "facts": {"checks": {"status": "out_of_scope"}, "inbox": {"by_source": {}}}, "steps": []}
    rows = joined_rows([a, zod_a], [b], verify, corpus)
    assert [(r["name"], r["run"]) for r in rows] == [("fst", "B1"), ("zod", "A")]
    table = joined_table(rows)
    assert len(table) == 4 and "L5 (v2; positive after deploy 3:abc123)" in table[2]


def test_comparison_with_campaign_12_cites_its_source_and_says_what_is_missing() -> None:
    baseline = json.loads((Path(__file__).parents[2] / "bench" / "campaign13" / "baseline-c12.json").read_text())
    lines = comparison(baseline, {"Level B runs with a pull request": {"dev": (2, 4)}}, [_b_record()])
    joined = "\n".join(lines)
    assert "decc9db" in joined
    assert "| Level B runs with a pull request | dev | 3/8 (38%, 95% CI 14-69%) | 2/4 (50%, 95% CI 15-85%) |" in joined
    assert "| Level B runs with a pull request | independent | 1/16 (6%, 95% CI 1-28%) | no record |" in joined
    assert "US$2.1 over 24 runs" in joined and "US$0.4 over 1 runs" in joined
