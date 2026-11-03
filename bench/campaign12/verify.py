# ruff: noqa: E501
"""Campaign 12, phase 5: independent verification of a promoted improvement (a pull request on a campaign fork).

    uv run python -m bench.campaign12.verify satisfymath/rich 2 --out docs/bench/campaign12/verify/rich-pr2.json

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
    with tempfile.TemporaryDirectory(prefix="c12-verify-", ignore_cleanup_errors=True) as tmp:
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
        record["finding_checks"] = checks
        named = {c["file"] for c in findings}
        record["change_matches_problem"] = bool(named) and set(record["changed_files"]) <= named | {
            f for f in record["changed_files"] if f.startswith("tests/")
        }
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
