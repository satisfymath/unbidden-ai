# ruff: noqa: E501
"""Campaign 13: plain public copies `satisfymath/c13-<name>` of the Level B repositories (the rule of campaign 12,
authorized by David on 2026-11-01, after the forks proved unable to start `pull_request` workflows). A copy is a new
repository, never a fork and never an existing one: the upstream commit pinned in the corpus is pushed as the
upstream's default branch, untouched (licenses, attribution and history as upstream holds them); provenance is the
repository's description and homepage; the only campaign change is ONE documented commit on top of the pin, per copy,
that removes what would publish, deploy, release or act as the project's bots, decided by one general rule
(`workflows.py`: the product's own publishing detection) instead of a list per repository: the team's test workflows
and jobs stay byte for byte, so CI runs on the agent's pull requests; a publishing job inside a test workflow is cut
out of the file. Dependabot's dynamic workflow is disabled in the settings (it opened five pull requests on c12-fst
within a minute of the push). Nothing goes upstream; no secret is ever added; no check of the code is removed or
replaced by one that always passes.

    uv run python -m bench.campaign13.copies bench/campaign13/corpus.yaml --repo fst        # one copy
    uv run python -m bench.campaign13.copies bench/campaign13/corpus.yaml --all             # every Level B repo
    uv run python -m bench.campaign13.copies bench/campaign13/corpus.yaml --repo fst --state  # what it holds
    uv run python -m bench.campaign13.copies bench/campaign13/corpus.yaml --repo fst --plan DIR  # the rule on a checkout
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import yaml

from bench.campaign13.common import LAB
from bench.campaign13.workflows import WorkflowPlan, plan_workflows, remove_jobs

GH = "satisfymath"
COPY_PREFIX = "c13-"  # campaign 12's copies were `c12-<name>`; they stay as campaign 12 left them
CAMPAIGN_AUTHOR = "Unbidden campaign 13"  # the author of each copy's one campaign commit (found again by name)
# In every copy: Dependabot's own workflow (it opened five pull requests on c12-fst within a minute of the push, each
# starting the full CI): its pull requests are not the agent's and its CI load would queue ahead of the agent's.
ALWAYS_DISABLE = ["dependabot-updates"]


def copy_slug(name: str) -> str:
    return f"{GH}/{COPY_PREFIX}{name}"


def workflow_files(checkout: Path) -> dict[str, str]:
    folder = checkout / ".github" / "workflows"
    if not folder.is_dir():
        return {}
    return {p.name: p.read_text(errors="replace") for p in sorted(folder.iterdir()) if p.suffix in (".yml", ".yaml")}


def apply_plan(checkout: Path, plans: list[WorkflowPlan]) -> tuple[list[str], list[dict[str, Any]]]:
    """The plans applied to a checkout's files (no git): removed files, and edited files with the jobs cut."""
    folder = checkout / ".github" / "workflows"
    removed: list[str] = []
    edited: list[dict[str, Any]] = []
    for plan in plans:
        path = folder / plan.file
        if plan.action == "remove" and path.exists():
            path.unlink()
            removed.append(plan.file)
        elif plan.action == "edit":
            before = path.read_text()
            after = remove_jobs(before, plan.removed_jobs)
            if after != before:
                path.write_text(after)
                edited.append({"file": f".github/workflows/{plan.file}", "removed_jobs": plan.removed_jobs,
                               "lines": [before.count("\n"), after.count("\n")]})  # fmt: skip
    return removed, edited


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


def ensure_copy(repo: dict[str, Any], human: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The copy exists with the pin as its default branch, its provenance written, its Actions configured; every
    step is idempotent and recorded as human preparation (minutes are what a person would spend clicking)."""
    human = human if human is not None else []
    slug = copy_slug(repo["name"])
    upstream = upstream_of(repo)
    branch = default_branch(upstream)
    description = (
        f"Campaign copy of {upstream} at {repo['commit'][:12]} for Unbidden campaign 13 (an engineering "
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
    state["prep"] = _prepare_commit(repo, slug, branch, human)
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
    by_file: dict[str, Any] = {}
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
    state |= {"workflows_registered": sorted(by_file), "disabled_in_settings": disabled,
              "kept": state["prep"].get("kept")}  # fmt: skip
    return state


def _prepare_commit(repo: dict[str, Any], slug: str, branch: str, human: list[dict[str, Any]]) -> dict[str, Any]:
    """The copy's one campaign commit: the rule of `workflows.py` applied to the pin's workflows; idempotent (no commit
    when the tree already is as planned). Everything else stays byte for byte."""
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
        f"user.name={CAMPAIGN_AUTHOR}",
        "-c",
        f"user.email={GH}@users.noreply.github.com",
    ]
    plans = plan_workflows(workflow_files(tmp))
    kept = [p.file + (f" (without {', '.join(p.removed_jobs)})" if p.action == "edit" else "")
            for p in plans if p.action != "remove"]  # fmt: skip
    removed, edited = apply_plan(tmp, plans)
    subprocess.run([*git, "add", "-A", ".github/workflows"], check=True)
    plan_record = [p.__dict__ for p in plans]
    staged = subprocess.run([*git, "diff", "--cached", "--quiet"], check=False).returncode == 1
    if not staged:
        return {"applied": False, "why": "nothing to change (already prepared, or nothing publishes)", "plan": plan_record,
                "kept": kept}  # fmt: skip
    why = {p.file: p.why for p in plans}
    lines = [
        f"campaign 13: {len(removed)} workflow file(s) removed, {len(edited)} without their publishing jobs",
        "",
        f"Human preparation of the campaign copy of {upstream_of(repo)} (pin {repo['commit'][:12]}, the parent of this",
        "commit). Removed because they would deploy, release, publish or act as the project's bots from this copy",
        "(one general rule, bench/campaign13/workflows.py):",
    ]
    lines += [f"  - {f}: {why.get(f, '')}" for f in removed]
    lines += [f"  - {e['file']}: jobs {', '.join(e['removed_jobs'])} cut out" for e in edited]
    lines += [
        "",
        f"Kept as upstream wrote them (the checks of the code): {', '.join(kept) or 'none'}.",
        "Nothing else changed; nothing goes upstream.",
        "",
        "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>",
    ]
    subprocess.run([*git, "commit", "-q", "-m", "\n".join(lines)], check=True)
    subprocess.run([*git, "push", "-q", "origin", branch], check=True, timeout=600)
    sha = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    human.append({"step": f"campaign commit {sha[:12]} on {slug}:{branch}: {len(removed)} workflow file(s) removed, "
                  f"{len(edited)} cut", "minutes": 5,
                  "why": "no deploy, release, package or bot runs from the copy; the checks stay as written"})  # fmt: skip
    return {"applied": True, "sha": sha, "removed": removed, "edited": edited, "plan": plan_record, "kept": kept}


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
        if parents == [repo["commit"]] and (c.get("commit") or {}).get("author", {}).get("name") == CAMPAIGN_AUTHOR:
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
            "body=Campaign 13: this run ended and the copy is restored to its base for the next run; the record keeps this pull request as it was.",
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
    parser.add_argument("--plan", help="print the workflow rule's plan for a local checkout (no GitHub call)")
    args = parser.parse_args()
    if args.plan:
        print(json.dumps([p.__dict__ for p in plan_workflows(workflow_files(Path(args.plan)))], indent=1))
        return
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
                    {"repo": repo["name"], **copy_state(copy_slug(repo["name"]), default_branch(upstream_of(repo)))},
                    indent=1,
                )
            )
            continue
        human: list[dict[str, Any]] = []
        state = ensure_copy(repo, human)
        print(json.dumps({"repo": repo["name"], **state, "human": human}, indent=1))


if __name__ == "__main__":
    main()
