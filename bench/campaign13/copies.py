# ruff: noqa: E501
"""Campaign 12: plain public copies `satisfymath/c12-<name>` of the Level B repositories (authorized by David on
2026-11-01, after the forks proved unable to start `pull_request` workflows). A copy is a new repository, never a
fork and never an existing one: the upstream commit pinned in the corpus is pushed as the upstream's default branch,
untouched (licenses, attribution and history as upstream holds them); provenance is the repository's description
and homepage; the only campaign change is ONE documented commit on top of the pin, per copy, that removes the
workflow files which would publish, deploy, release or act as the project's bots (listed here per repository with
why; GitHub registers a workflow only once an event triggers it, so `deploy.yml` could not be disabled in the
Actions settings before the first merge would have run it) and, for Spoolman, cuts the two publishing jobs out of
`ci.yml` (its test jobs byte for byte as upstream wrote them). Dependabot's dynamic workflow is disabled in the
settings (it opened five pull requests on c12-fst within a minute of the push). Nothing goes upstream; no secret is
ever added; no check of the code is removed or replaced by one that always passes.

    uv run python -m bench.campaign13.copies bench/campaign13/corpus.yaml --repo fst        # one copy
    uv run python -m bench.campaign13.copies bench/campaign13/corpus.yaml --all             # every Level B repo
    uv run python -m bench.campaign13.copies bench/campaign13/corpus.yaml --repo fst --state  # what it holds
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

import yaml

from bench.campaign13.common import LAB

GH = "satisfymath"
# In every copy: Dependabot's own workflow (it opened five pull requests on c12-fst within a minute of the push, each
# starting the full CI): its pull requests are not the agent's and its CI load would queue ahead of the agent's.
ALWAYS_DISABLE = ["dependabot-updates"]

# What each copy's campaign commit removes from `.github/workflows` and why; the project's checks of the code are
# never in this list. Read before the freeze; frozen with the harness.
COPIES: dict[str, dict[str, Any]] = {
    "fst": {
        "disable": [
            "deploy.yml",  # push to master: deploys to FastAPI Cloud with the project's secrets
            "deploy-docker-compose.yml",  # dispatch: a deploy with secrets
            "prepare-release.yml",  # dispatch: a release
            "create-draft-release.yml",  # a merged PR labelled `release` creates a draft release
            "add-to-project.yml",  # the project's board bot (PROJECTS_TOKEN)
            "issue-manager.yml",  # the project's issue bot
            "smokeshow.yml",  # coverage upload with SMOKESHOW_AUTH_KEY
            "bump-pre-commit-hooks.yml",  # scheduled: opens pull requests on its own
        ],
        "kept": "test-backend, test-docker-compose, playwright, pre-commit, zizmor, detect-conflicts, guard-dependencies",
    },
    "spoolman": {
        "disable": [
            "apidocs.yml",  # release: deploys the API docs
            "sponsors.yml",  # schedule, PAT
            "sponsor-label.yml",  # issues, PAT
            "trigger-release.yml",  # dispatch: a release
            "issue-manager.yml",  # the project's issue bot
            "weblate-automerge.yml",  # auto-merges Weblate pull requests
        ],
        "edit": {
            "file": ".github/workflows/ci.yml",
            "remove_jobs": ["publish-images", "publish-release"],
            "why": "on a push to master `ci.yml` publishes images to ghcr.io and Docker Hub and a GitHub release; "
            "the style, build and test jobs are left exactly as upstream wrote them",
        },
        "kept": "ci.yml (style, build-client, build-amd64, build-tester, test, test-frontend, test-frontend-v2, "
        "build-arm64, build-armv7, test-multiarch-smoke), guard-translations",
    },
    "rich": {
        "disable": [
            "readmechanged.yml",  # push to master: a notification with GHP_README_WORKFLOW
            "comment.yml",  # issues bot
            "newissue.yml",  # issues bot
        ],
        "kept": "pythonpackage (tests on the matrix), codespell; codeql filters on `master` and will not run",
    },
    "marshmallow": {"disable": [], "kept": "build-release (tests, build; publish only on tags)"},
    "misago": {"disable": ["publish.yml"], "kept": "tests"},  # release: PyPI
    "brightbean-studio": {"disable": [], "kept": "ci (lint, typecheck, test, build with push: false, secrets-scan)"},
    "traefik-manager": {
        "disable": [
            "docker.yml",  # push to dev/refactor: images to ghcr.io
            "release-binaries.yml",  # release
        ],
        "kept": "tests (pytest, go), audit; pr-base-check skips the repository owner's pull requests",
    },
    "oauthlib": {
        "disable": [],
        "kept": "python-build (tests, docs, build; publish gated on oauthlib/oauthlib and tags), lint_python, dependency-review",
    },
    "rdflib": {
        "disable": [
            "docker-images.yaml",  # push to main: images to ghcr.io (the PR-time image build is lost with it)
        ],
        "kept": "validate (tests, extra-tasks, coverage), test-report",
    },
    "graphtage": {
        "disable": [
            "publish_docs.yml",  # push to master: deploys the docs site
            "pythonpublish.yml",  # release: PyPI
        ],
        "kept": "pythonpackage (lint, build), pip-audit, artifacts (binaries; upload only on tags)",
    },
    "harlequin": {
        "disable": [
            "publish.yml",  # merged release/* pull requests: PyPI and a release
            "publish-artifacts.yml",  # called by publish
            "release.yml",  # dispatch: a release
        ],
        "kept": "test, static, test-build",
    },
    "pipx": {
        "disable": [
            "release.yml",  # tags: PyPI and a release
            "pre-release.yml",  # dispatch, release app key
            "upgrade-release-tools.yaml",  # schedule, release app key
        ],
        "kept": "tests, zizmor, codeql, news (changelog fragment check: the project's own rule)",
    },
}


def gh(*args: str, timeout: int = 120, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    token = subprocess.run(["gh", "auth", "token", "-u", GH], capture_output=True, text=True, check=True).stdout.strip()
    return subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        input=stdin,
        env={**os.environ, "GH_TOKEN": token},
    )


def upstream_of(repo: dict[str, Any]) -> str:
    return repo["url"].removeprefix("https://github.com/").removesuffix(".git")


def default_branch(upstream: str) -> str:
    out = gh("api", f"repos/{upstream}", "--jq", ".default_branch")
    if out.returncode != 0:
        raise RuntimeError(f"cannot read {upstream}: {out.stderr[-200:]}")
    return out.stdout.strip()


def _remove_jobs(text: str, names: list[str]) -> str:
    """A workflow file without the named jobs: each job block (two-space indentation under `jobs:`) is cut whole;
    everything else stays byte for byte."""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    skipping = False
    for line in lines:
        if re.match(r"^  [A-Za-z0-9_-]+:\s*$", line):
            skipping = line.strip().rstrip(":") in names
        elif skipping and re.match(r"^\S", line):
            skipping = False
        if not skipping:
            out.append(line)
    return "".join(out)


def ensure_copy(repo: dict[str, Any], human: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The copy exists with the pin as its default branch, its provenance written, its Actions configured; every
    step is idempotent and recorded as human preparation (minutes are what a person would spend clicking)."""
    human = human if human is not None else []
    name = f"c12-{repo['name']}"
    slug = f"{GH}/{name}"
    upstream = upstream_of(repo)
    branch = default_branch(upstream)
    plan = COPIES.get(repo["name"], {"disable": [], "kept": "every workflow"})
    description = (
        f"Campaign copy of {upstream} at {repo['commit'][:12]} for Unbidden campaign 12 (an engineering "
        f"agent validated on an installed product). Not the project: see {repo['url']}. Pull requests here "
        f"are the agent's; nothing goes upstream."
    )
    state: dict[str, Any] = {"slug": slug, "base": branch, "upstream": upstream, "kind": "copy", "created": False}
    exists = gh("api", f"repos/{slug}")
    # a renamed repository leaves a redirect: `repos/<slug>` answers with another full_name; that is not this copy
    info = json.loads(exists.stdout) if exists.returncode == 0 else {}
    if info and info.get("full_name", "").lower() == slug.lower():
        if info.get("fork"):
            raise RuntimeError(f"{slug} is a fork, not a copy: refusing to use it")
    else:
        made = gh(
            "repo",
            "create",
            slug,
            "--public",
            "--description",
            description,
            "--homepage",
            repo["url"],
            "--disable-wiki",
        )
        if made.returncode != 0:
            raise RuntimeError(f"could not create {slug}: {made.stderr[-300:]}")
        state["created"] = True
        human.append(
            {"step": f"create the public copy {slug}", "minutes": 1, "why": "pull requests, CI and merges off upstream"}
        )
        time.sleep(3)
    gh("repo", "edit", slug, "--description", description, "--homepage", repo["url"])
    # the pin as the default branch, from a throwaway clone that fetched only that commit from upstream
    head = gh("api", f"repos/{slug}/branches/{branch}", "--jq", ".commit.sha")
    if head.returncode != 0 or not head.stdout.strip():
        tmp = LAB / "copy-push" / repo["name"]
        if tmp.exists():
            subprocess.run(["rm", "-rf", str(tmp)], check=True)
        tmp.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(tmp)], check=True)
        subprocess.run(["git", "-C", str(tmp), "remote", "add", "origin", repo["url"]], check=True)
        subprocess.run(["git", "-C", str(tmp), "fetch", "-q", "origin", repo["commit"]], check=True, timeout=3600)
        subprocess.run(["git", "-C", str(tmp), "remote", "add", "copy", f"git@github-{GH}:{slug}.git"], check=True)
        push = subprocess.run(
            ["git", "-C", str(tmp), "push", "-q", "copy", f"{repo['commit']}:refs/heads/{branch}"],
            capture_output=True,
            text=True,
            timeout=3600,
        )
        if push.returncode != 0:
            raise RuntimeError(f"could not push the pin to {slug}:{branch}: {push.stderr[-300:]}")
        human.append(
            {"step": f"push the pin {repo['commit'][:12]} to {slug}:{branch}", "minutes": 1, "why": "the copy's base"}
        )
        time.sleep(3)
        gh("repo", "edit", slug, "--default-branch", branch)
    # the campaign commit: workflow files removed (and Spoolman's ci.yml cut), once, documented, on top of the pin
    state["prep"] = _prepare_commit(repo, slug, branch, plan, human)
    state["pin"] = repo["commit"]
    # the base must be exactly pin + campaign commit: after a run (a merge moved it) it is put back there, the
    # agent's branches deleted and its open pull requests closed (the records already hold them; GitHub keeps them)
    state["restore"] = restore_base(repo, slug, branch, human)
    state["base_sha"] = state["restore"]["base_sha"]
    state["pin_in_history"] = state["restore"]["pin_in_history"]
    # Dependabot: its dynamic workflow disabled, security pull requests off (settings, no commit), and whatever pull
    # requests it opened before that closed (not the agent's; never counted)
    gh("api", "-X", "DELETE", f"repos/{slug}/automated-security-fixes")
    bots = gh(
        "api",
        f"repos/{slug}/pulls?state=open&per_page=50",
        "--jq",
        '[.[] | select(.user.login == "dependabot[bot]") | .number]',
    )
    for number in json.loads(bots.stdout or "[]"):
        gh("api", "-X", "PATCH", f"repos/{slug}/pulls/{number}", "-f", "state=closed")
    state["dependabot_prs_closed"] = json.loads(bots.stdout or "[]")
    disabled: list[str] = []
    for attempt in range(3):
        listed = gh("api", f"repos/{slug}/actions/workflows?per_page=100", "--jq", "[.workflows[] | {id, path, state}]")
        by_file = {Path(w["path"]).name: w for w in json.loads(listed.stdout or "[]")}
        if any(f in by_file for f in ALWAYS_DISABLE) or attempt == 2:
            break
        time.sleep(10)
    for file in ALWAYS_DISABLE:
        w = by_file.get(file)
        if w is not None:
            if w["state"] != "disabled_manually":
                gh("api", "-X", "PUT", f"repos/{slug}/actions/workflows/{w['id']}/disable")
            disabled.append(file)
    state |= {"workflows_registered": sorted(by_file), "disabled_in_settings": disabled, "kept": plan.get("kept")}
    return state


def _prepare_commit(
    repo: dict[str, Any], slug: str, branch: str, plan: dict[str, Any], human: list[dict[str, Any]]
) -> dict[str, Any]:
    """The copy's one campaign commit: the listed workflow files removed, Spoolman's `ci.yml` without its publishing
    jobs; idempotent (no commit when the tree already is as planned). Everything else stays byte for byte."""
    tmp = LAB / "copy-prep" / repo["name"]
    if tmp.exists():
        subprocess.run(["rm", "-rf", str(tmp)], check=True)
    tmp.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "-q", "--depth", "5", "--branch", branch, f"git@github-{GH}:{slug}.git", str(tmp)],
                   check=True, timeout=600)  # fmt: skip
    git = [
        "git",
        "-C",
        str(tmp),
        "-c",
        "user.name=Unbidden campaign 12",
        "-c",
        f"user.email={GH}@users.noreply.github.com",
    ]
    removed: list[str] = []
    for file in plan.get("disable", []):
        path = tmp / ".github" / "workflows" / file
        if path.exists():
            subprocess.run([*git, "rm", "-q", str(path)], check=True)
            removed.append(file)
    edit = plan.get("edit")
    edited: dict[str, Any] | None = None
    if edit:
        path = tmp / edit["file"]
        before = path.read_text()
        after = _remove_jobs(before, edit["remove_jobs"])
        if after != before:
            path.write_text(after)
            subprocess.run([*git, "add", edit["file"]], check=True)
            edited = {
                "file": edit["file"],
                "removed_jobs": edit["remove_jobs"],
                "lines": [before.count("\n"), after.count("\n")],
            }
    staged = subprocess.run([*git, "diff", "--cached", "--quiet"], check=False).returncode == 1
    if not staged:
        return {"applied": False, "why": "nothing to change (already prepared, or nothing listed)"}
    lines = [
        f"campaign 12: {len(removed)} workflow file(s) removed"
        + (f"; {edit['file']} without its publishing jobs" if edited else ""),
        "",
        f"Human preparation of the campaign copy of {upstream_of(repo)} (pin {repo['commit'][:12]}, the parent of this",
        "commit). Removed because they would deploy, release, publish or act as the project's bots from this copy:",
    ]
    lines += [f"  - {f}" for f in removed]
    if edited:
        lines += ["", f"{edit['file']}: jobs {', '.join(edit['remove_jobs'])} cut out; {edit['why']}."]
    lines += [
        "",
        f"Kept as upstream wrote them (the checks of the code): {plan.get('kept', 'every other workflow')}.",
        "Nothing else changed; nothing goes upstream.",
        "",
        "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>",
    ]
    subprocess.run([*git, "commit", "-q", "-m", "\n".join(lines)], check=True)
    subprocess.run([*git, "push", "-q", "origin", branch], check=True, timeout=600)
    sha = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    human.append({"step": f"campaign commit {sha[:12]} on {slug}:{branch}: {len(removed)} workflow file(s) removed"
                  + (f", {edit['file']} cut" if edited else ""), "minutes": 5,
                  "why": "no deploy, release, package or bot runs from the copy; the checks stay as written"})  # fmt: skip
    return {"applied": True, "sha": sha, "removed": removed, "edited": edited}


def campaign_head(repo: dict[str, Any], slug: str, branch: str) -> tuple[str | None, bool]:
    """The commit the base should be at (the campaign commit whose parent is the pin, else the pin itself) and
    whether the pin is in the branch's history."""
    cmp = gh("api", f"repos/{slug}/compare/{repo['commit']}...{branch}")
    if cmp.returncode != 0:
        return None, False
    data = json.loads(cmp.stdout)
    in_history = data.get("status") in ("ahead", "identical")
    for c in data.get("commits") or []:
        parents = [p["sha"] for p in c.get("parents") or []]
        if (
            parents == [repo["commit"]]
            and (c.get("commit") or {}).get("author", {}).get("name") == "Unbidden campaign 12"
        ):
            return c["sha"], in_history
    return (repo["commit"] if in_history else None), in_history


def restore_base(repo: dict[str, Any], slug: str, branch: str, human: list[dict[str, Any]]) -> dict[str, Any]:
    """The copy as a run must find it: base at pin + campaign commit, no `unbidden/*` branch, no open agent pull
    request. Done only when something differs; everything closed or moved stays readable on GitHub."""
    expected, in_history = campaign_head(repo, slug, branch)
    head = gh("api", f"repos/{slug}/branches/{branch}", "--jq", ".commit.sha").stdout.strip()
    out: dict[str, Any] = {
        "expected": expected,
        "head_before": head,
        "pin_in_history": in_history,
        "closed": [],
        "deleted": [],
    }
    if expected is None:
        out["error"] = "the pin is not in the base's history: not touched"
        out["base_sha"] = head
        return out
    prs = gh(
        "api",
        f"repos/{slug}/pulls?state=open&base={branch}&per_page=50",
        "--jq",
        '[.[] | select(.head.ref | startswith("unbidden/")) | .number]',
    )
    for number in json.loads(prs.stdout or "[]"):
        gh("api", "-X", "PATCH", f"repos/{slug}/pulls/{number}", "-f", "state=closed")
        gh(
            "api",
            "-X",
            "POST",
            f"repos/{slug}/issues/{number}/comments",
            "-f",
            "body=Campaign 12: this run ended and the copy is restored to its base for the next run; the record keeps this pull request as it was.",
        )
        out["closed"].append(number)
    branches = gh("api", f"repos/{slug}/branches?per_page=100", "--jq", '[.[].name | select(startswith("unbidden/"))]')
    for name in json.loads(branches.stdout or "[]"):
        gh("api", "-X", "DELETE", f"repos/{slug}/git/refs/heads/{name}")
        out["deleted"].append(name)
    if head != expected:
        tmp = LAB / "copy-restore" / repo["name"]
        if tmp.exists():
            subprocess.run(["rm", "-rf", str(tmp)], check=True)
        tmp.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(tmp)], check=True)
        subprocess.run(["git", "-C", str(tmp), "remote", "add", "copy", f"git@github-{GH}:{slug}.git"], check=True)
        subprocess.run(["git", "-C", str(tmp), "fetch", "-q", "copy", branch], check=True, timeout=1800)
        push = subprocess.run(
            ["git", "-C", str(tmp), "push", "-q", "--force", "copy", f"{expected}:refs/heads/{branch}"],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if push.returncode != 0:
            out["error"] = f"could not restore the base: {push.stderr[-300:]}"
        else:
            human.append(
                {
                    "step": f"restore {slug}:{branch} to {expected[:12]} (pin + campaign commit); {len(out['closed'])} PR(s) closed, {len(out['deleted'])} branch(es) deleted",
                    "minutes": 1,
                    "why": "every run starts from the same base",
                }
            )
    out["base_sha"] = gh("api", f"repos/{slug}/branches/{branch}", "--jq", ".commit.sha").stdout.strip()
    return out


def copy_state(slug: str, base: str) -> dict[str, Any]:
    """What the copy holds, read apart from Unbidden's records: pull requests against the base with their head
    commit, merge state and the check runs on that exact head; the campaign branches; the base's head."""
    prs = gh(
        "api",
        f"repos/{slug}/pulls?state=all&base={base}&per_page=50",
        "--jq",
        "[.[] | {number, state, merged_at, merge_commit_sha, head: .head.ref, head_sha: .head.sha, title, created_at, user: .user.login}]",
    )
    branches = gh("api", f"repos/{slug}/branches?per_page=100", "--jq", '[.[].name | select(startswith("unbidden/"))]')
    head = gh("api", f"repos/{slug}/branches/{base}", "--jq", ".commit.sha")
    try:
        pulls = json.loads(prs.stdout or "[]")
    except ValueError:
        return {"error": (prs.stderr or branches.stderr)[-300:]}
    for pr in pulls:
        pr["checks"] = check_runs(slug, pr["head_sha"])
    try:
        unbidden_branches = json.loads(branches.stdout or "[]")
    except ValueError:
        unbidden_branches = []
    return {"pulls": pulls, "unbidden_branches": unbidden_branches, "base_head": head.stdout.strip()}


def check_runs(slug: str, sha: str) -> list[dict[str, Any]]:
    out = gh(
        "api",
        f"repos/{slug}/commits/{sha}/check-runs?per_page=100",
        "--jq",
        "[.check_runs[] | {name, status, conclusion, head_sha, started_at, completed_at, html_url}]",
    )
    try:
        return json.loads(out.stdout or "[]")
    except ValueError:
        return []


def ci_pending(slug: str, base: str) -> bool:
    """Whether an open pull request against the base still has CI to come: check runs not completed, or none yet on
    a pull request younger than 15 minutes (GitHub takes a moment to start them). Used by the harness only to keep
    observing a cycle: the agent is never told."""
    state = copy_state(slug, base)
    for pr in state.get("pulls", []):
        if pr.get("state") != "open":
            continue
        runs = pr.get("checks") or []
        if any(r.get("status") != "completed" for r in runs):
            return True
        if not runs:
            created = time.strptime(pr["created_at"], "%Y-%m-%dT%H:%M:%SZ")
            if time.time() - time.mktime(created) + time.timezone < 15 * 60:
                return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("corpus")
    parser.add_argument("--repo")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--state", action="store_true")
    args = parser.parse_args()
    corpus = yaml.safe_load(Path(args.corpus).read_text())
    repos = (
        [r for r in corpus["repos"] if r.get("level_b")]
        if args.all
        else [r for r in corpus["repos"] if r["name"] == args.repo]
    )
    for repo in repos:
        if args.state:
            print(
                json.dumps(
                    {"repo": repo["name"], **copy_state(f"{GH}/c12-{repo['name']}", default_branch(upstream_of(repo)))},
                    indent=1,
                )
            )
            continue
        human: list[dict[str, Any]] = []
        state = ensure_copy(repo, human)
        print(json.dumps({"repo": repo["name"], **state, "human": human}, indent=1))


if __name__ == "__main__":
    main()
