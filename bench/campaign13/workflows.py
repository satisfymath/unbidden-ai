"""Which of a repository's workflows a campaign copy keeps (campaign 13): the team's checks stay as written, so CI runs
on the agent's pull requests; what would publish, deploy, release or act as the project's bots goes. The rule is
general (no list per repository): it reuses the product's own publishing detection (`unbidden/sandbox/ci_env.py`,
`PUBLISH_USES` and `publishes()`), the one that leaves those steps out of a CI job the sandbox replays.

Per job: a job that runs the tests is kept, whatever else it does (a coverage upload in a test job fails harmlessly
without the project's secrets). A job that does not run tests is removed when one of its steps publishes, or its id or
name says deploy/release/publish; a removed job that a kept job `needs` is kept after all. Per workflow: removed when
no job is left, or when nothing triggers it on code (no `push`, `pull_request`, `merge_group` or `workflow_call`):
release, schedule, issue and dispatch workflows check no pull request and are where bots and releases live.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import yaml

from unbidden.sandbox.ci_env import PUBLISH_USES, publishes, runs_tests

CODE_TRIGGERS = {"push", "pull_request", "merge_group", "workflow_call"}
HARMLESS_USES = re.compile(r"actions/(?:checkout|cache|setup-|upload-artifact|download-artifact)|setup-", re.I)
PUBLISH_NAME = re.compile(r"deploy|release|publish|pypi|docker-?hub|ghcr|pages", re.I)
_BUILD_PUSH = re.compile(r"docker/build-push-action", re.I)


@dataclass
class WorkflowPlan:
    """What a copy does with one workflow file: keep it whole, remove it, or cut some jobs out."""

    file: str
    action: str  # "keep", "remove" or "edit"
    removed_jobs: list[str] = field(default_factory=list[str])
    kept_jobs: list[str] = field(default_factory=list[str])
    why: str = ""


def _triggers(data: dict[Any, Any]) -> set[str]:
    on = data.get("on", data.get(True))  # PyYAML reads a bare `on:` key as the boolean True
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return {str(t) for t in on}
    if isinstance(on, dict):
        return {str(t) for t in on}
    return set()


def step_publishes(step: dict[str, Any]) -> bool:
    uses = str(step.get("uses", ""))
    if uses and _BUILD_PUSH.search(uses):
        push = (step.get("with") or {}).get("push")
        return push not in (None, False, "false")  # an image built and not pushed is a check
    if uses and PUBLISH_USES.search(uses) and not HARMLESS_USES.search(uses):
        return True
    return publishes(str(step.get("run", "")))


def job_runs_tests(job: dict[str, Any]) -> bool:
    for step in job.get("steps") or []:
        if isinstance(step, dict) and runs_tests(str(step.get("name", "")), str(step.get("run", ""))):
            return True
    return False


def job_publishes(job_id: str, job: dict[str, Any]) -> bool:
    if job_runs_tests(job):
        return False
    if PUBLISH_NAME.search(job_id) or PUBLISH_NAME.search(str(job.get("name", ""))):
        return True
    if "uses" in job and PUBLISH_NAME.search(str(job["uses"])):  # a reusable workflow named for a release
        return True
    return any(isinstance(s, dict) and step_publishes(s) for s in job.get("steps") or [])


def _needs(job: dict[str, Any]) -> set[str]:
    needs = job.get("needs")
    if isinstance(needs, str):
        return {needs}
    return {str(n) for n in needs} if isinstance(needs, list) else set()


def plan_workflow(file: str, text: str) -> WorkflowPlan:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return WorkflowPlan(file, "keep", why=f"unreadable YAML, kept as written ({str(exc)[:80]})")
    if not isinstance(data, dict):
        return WorkflowPlan(file, "keep", why="not a workflow mapping, kept")
    jobs: dict[str, Any] = {str(k): v for k, v in (data.get("jobs") or {}).items() if isinstance(v, dict)}
    triggers = _triggers(data)
    if not triggers & CODE_TRIGGERS:
        why = f"triggered only by {', '.join(sorted(triggers)) or 'nothing'}: checks no code"
        return WorkflowPlan(file, "remove", removed_jobs=sorted(jobs), why=why)
    removed = {j for j, d in jobs.items() if job_publishes(j, d)}
    changed = True
    while changed:  # a removed job that a kept one needs stays
        changed = False
        for j, d in jobs.items():
            if j not in removed and (_needs(d) & removed):
                removed -= _needs(d)
                changed = True
    kept = [j for j in jobs if j not in removed]
    if not removed:
        return WorkflowPlan(file, "keep", kept_jobs=kept, why="the team's checks")
    if not kept:
        return WorkflowPlan(
            file, "remove", removed_jobs=sorted(removed), why="every job publishes, deploys or releases"
        )
    return WorkflowPlan(file, "edit", removed_jobs=sorted(removed), kept_jobs=kept,
                        why="publishing jobs cut out; the checks stay byte for byte")  # fmt: skip


def plan_workflows(files: dict[str, str]) -> list[WorkflowPlan]:
    """One plan per workflow file (name -> text), in name order."""
    return [plan_workflow(name, files[name]) for name in sorted(files)]


def remove_jobs(text: str, names: list[str]) -> str:
    """A workflow file without the named jobs: each job block under `jobs:` (at whatever indentation the file uses)
    is cut whole, with the comment lines just above it; everything else stays byte for byte."""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    held: list[str] = []  # comment and blank lines between jobs: they go with the job that follows
    in_jobs = False
    indent: str | None = None
    skipping = False
    for line in lines:
        if re.match(r"^jobs:\s*(#.*)?$", line):
            in_jobs, skipping = True, False
            out.append(line)
            continue
        if in_jobs and re.match(r"^\S", line) and not line.startswith("#"):  # the next top-level key ends `jobs:`
            in_jobs, skipping = False, False
            out += held
            held = []
        if in_jobs:
            m = re.match(r"^(\s+)([A-Za-z0-9_-]+|\"[^\"]+\"|'[^']+'):\s*(#.*)?$", line)
            if m and (indent is None or m.group(1) == indent):
                indent = m.group(1)
                skipping = m.group(2).strip("\"'") in names
                if not skipping:
                    out += held
                held = []
            elif indent is not None and (not line.strip() or re.match(rf"^{indent}#", line)):
                held.append(line)
                continue
        if not skipping:
            out += held
            held = []
            out.append(line)
    if not skipping:
        out += held
    return "".join(out)
