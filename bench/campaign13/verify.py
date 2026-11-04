# ruff: noqa: E501
"""Campaign 12, phase 5: independent verification of a promoted improvement (a pull request on a campaign fork).

    uv run python -m bench.campaign13.verify satisfymath/rich 2 --out docs/bench/campaign13/verify/rich-pr2.json

Apart from the agent's own run and its evaluator: (1) the problem exists at the base and is gone at the head, checked
by running ruff/mypy ourselves on the file and rule the pull request names; (2) the change corresponds to the problem
(only the named files change; no test file is deleted; no `skip`/`xfail` is added); (3) the project's own checks run
on the head commit in a fresh sandbox (`bench.checks_only`: the product's preparation routine, called here without
the agent, on a throwaway clone); (4) the pull request's head equals the proposal's commit. What cannot be checked is
marked "no independent confirmation"; nothing is inferred from the pull request's text alone.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

FINDING = re.compile(r"`(?P<file>[^`:]+):(?P<line>\d+)` (?P<rule>[A-Z]+\d+)")


def gh(*args: str) -> str:
    token = subprocess.run(["gh", "auth", "token", "-u", "satisfymath"], capture_output=True, text=True, check=True)
    out = subprocess.run(["gh", *args], capture_output=True, text=True, check=False,
                         env={**os.environ, "GH_TOKEN": token.stdout.strip()})  # fmt: skip
    return out.stdout


def ruff_findings(repo: Path, rev: str, file: str, rule: str) -> list[str] | None:
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "--detach", rev], check=True)
    out = subprocess.run(["uvx", "ruff", "check", "--select", rule, "--output-format", "concise", file], cwd=repo,
                         capture_output=True, text=True, check=False)  # fmt: skip
    if out.returncode not in (0, 1):
        return None
    return [line for line in out.stdout.splitlines() if f" {rule} " in line or line.endswith(rule)]


BUMP = re.compile(r"bump (?P<package>[\w.\-\[\]]+) (?P<old>[^\s→]+) → (?P<new>[^\s()]+)")
DEPENDENCY_FILES = re.compile(
    r"(^|/)(uv\.lock|poetry\.lock|pyproject\.toml|setup\.cfg|Pipfile(\.lock)?|requirements[^/]*\.(txt|in))$"
)


def osv_ids(package: str, version: str) -> set[str] | None:
    """The advisories OSV (osv.dev, a source the product does not use) lists for a PyPI package at a version."""
    import urllib.request

    query = json.dumps({"package": {"name": package, "ecosystem": "PyPI"}, "version": version}).encode()
    request = urllib.request.Request("https://api.osv.dev/v1/query", data=query,
                                     headers={"Content-Type": "application/json"})  # fmt: skip
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            vulns = json.loads(response.read()).get("vulns") or []
    except OSError:
        return None
    return {v["id"] for v in vulns} | {a for v in vulns for a in v.get("aliases") or []}


def bump_check(title: str, files: list[dict[str, Any]], repo: Path, head: str) -> dict[str, Any] | None:
    """A security bump, checked apart from the product: OSV lists advisories for the old version and none of them for
    the new one; the pull request changes only dependency files, and its patch names the new version."""
    found = BUMP.search(title)
    if found is None:
        return None
    package, old, new = found["package"], found["old"], found["new"]
    before, after = osv_ids(package, old), osv_ids(package, new)
    patches = "\n".join(f.get("patch") or "" for f in files)
    # GitHub leaves out the patch of a large file (a uv.lock): then the file itself, at the head, is read.
    pinned = new in patches or any(
        new
        in subprocess.run(
            ["git", "-C", str(repo), "show", f"{head}:{f['filename']}"], capture_output=True, text=True, check=False
        ).stdout
        for f in files
        if not f.get("patch")
    )
    only_deps = all(DEPENDENCY_FILES.search(f["filename"]) for f in files)
    if before is None or after is None:
        verdict = "no independent confirmation"
    elif before and not (before & after) and pinned and only_deps:
        verdict = "confirmed"
    else:
        verdict = "NOT confirmed"
    return {"rule": "advisories (OSV)", "file": package, "at_base": sorted(before or []), "at_head": sorted(after or []),
            "new_version_in_patch": pinned, "only_dependency_files": only_deps, "verdict": verdict}  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("slug")
    parser.add_argument("number", type=int)
    parser.add_argument("--out", required=True)
    parser.add_argument("--checks", action="store_true", help="also run the project's own checks on the head (slow)")
    args = parser.parse_args()
    pr = json.loads(gh("api", f"repos/{args.slug}/pulls/{args.number}"))
    files = json.loads(gh("api", f"repos/{args.slug}/pulls/{args.number}/files"))
    body = pr.get("body") or ""
    findings = [m.groupdict() for m in FINDING.finditer(body)]
    record: dict[str, Any] = {
        "slug": args.slug, "number": args.number, "title": pr["title"], "base": pr["base"]["sha"], "head": pr["head"]["sha"],
        "claims": findings, "changed_files": [f["filename"] for f in files],
        "tests_deleted": [f["filename"] for f in files if f["status"] == "removed" and "test" in f["filename"]],
        "skips_added": [f["filename"] for f in files if re.search(r"^\+.*(pytest\.mark\.(skip|xfail)|@skip)", f.get("patch") or "", re.M)],
    }  # fmt: skip
    # ignore_cleanup_errors: spoolman's clone (phase 7) left a directory macOS reported as not empty at cleanup, and
    # the record was lost with it; the verdict matters, the temp directory does not.
    with tempfile.TemporaryDirectory(prefix="c13-verify-", ignore_cleanup_errors=True) as tmp:
        repo = Path(tmp) / "repo"
        subprocess.run(["git", "clone", "-q", f"https://github.com/{args.slug}.git", str(repo)], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "fetch", "-q", "origin", pr["head"]["sha"], pr["base"]["sha"]], check=True
        )
        checks: list[dict[str, Any]] = []
        for claim in findings:
            before = ruff_findings(repo, pr["base"]["sha"], claim["file"], claim["rule"])
            after = ruff_findings(repo, pr["head"]["sha"], claim["file"], claim["rule"])
            checks.append({
                **claim,
                "at_base": before, "at_head": after,
                "verdict": "confirmed" if before and not after else ("no independent confirmation" if before is None or after is None else "NOT confirmed"),
            })  # fmt: skip
        bump = bump_check(pr["title"], files, repo, pr["head"]["sha"]) if not findings else None
        if bump is not None:
            checks.append(bump)
        record["finding_checks"] = checks
        named = {c["file"] for c in findings}
        record["change_matches_problem"] = (
            bump["only_dependency_files"]
            if bump is not None
            else bool(named)
            and set(record["changed_files"]) <= named | {f for f in record["changed_files"] if f.startswith("tests/")}
        )
        if args.checks:
            from bench.checks_only import checks as project_checks

            rec = project_checks(repo, pr["head"]["sha"], ["pypi.org", "files.pythonhosted.org", "deb.debian.org"])
            record["project_checks_on_head"] = {
                k: rec.get(k) for k in ("status", "collected", "failed", "why", "scope")
            }
    verdict = (
        "verified"
        if checks
        and all(c["verdict"] == "confirmed" for c in checks)
        and record["change_matches_problem"]
        and not record["tests_deleted"]
        and not record["skips_added"]
        and (not args.checks or record.get("project_checks_on_head", {}).get("status") == "passed")
        else "no independent confirmation"
        if not checks or any(c["verdict"] == "no independent confirmation" for c in checks)
        else "NOT verified"
    )
    record["verdict"] = verdict
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=1, ensure_ascii=False, default=str))
    print(json.dumps({"pr": args.number, "verdict": verdict, "findings": [(c["rule"], c["file"], c["verdict"]) for c in checks],
                      "tests_deleted": record["tests_deleted"], "skips_added": record["skips_added"],
                      "project_checks": record.get("project_checks_on_head", {}).get("status")}, ensure_ascii=False))  # fmt: skip


if __name__ == "__main__":
    main()
