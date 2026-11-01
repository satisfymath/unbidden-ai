"""How reproducible a robustness probe's finding is, and how often a fresh probe finds it.

    uv run python -m bench.probe_variance <workspace> <package> --direct "<python statement>" \\
        [--replay tests.py] [--seeds 10] [--fresh 10] --out docs/bench/<name>

Three measurements, each recorded with what it ran (statement, test file digest, seed, model, prompt, image):

1. **Direct.** One statement run in the sandbox: does the crash happen at all, deterministically?
2. **Replay.** A test file that found it, run under Hypothesis seeds 0..N-1: does the same file find it again?
3. **Fresh.** N probes as the autonomous cycle runs them (the model writes new tests each time, seed 0): how often
   is it found? This is the detection rate a single probe per commit has.

Remote calls are tagged `bench:probe-variance:<package>` in the spend ledger.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bench.scale import unbidden_version


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace")
    parser.add_argument("package", help="as the probe names it, e.g. src/humanize")
    parser.add_argument("--direct", help="a Python statement that should crash, run once")
    parser.add_argument("--replay", help="a test file that found the crash")
    parser.add_argument("--seeds", type=int, default=10)
    parser.add_argument("--fresh", type=int, default=10)
    parser.add_argument("--exception", default="KeyError", help="the crash looked for")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    os.environ["UNBIDDEN_RUN"] = f"bench:probe-variance:{Path(args.package).name}"

    from unbidden.brain.prompts import load_prompt
    from unbidden.contracts.llm import Tier
    from unbidden.research.robustness import RobustnessProbe, parse_crashes
    from unbidden.runtime import Runtime
    from unbidden.sandbox.provision import link_dependencies, sandbox_spec
    from unbidden.sandbox.runner import SandboxRunner, discard, snapshot
    from unbidden.workspace import Workspace, head_sha

    runtime = Runtime.open(Workspace.find(Path(args.workspace).expanduser()))
    rev = head_sha(runtime.workspace.repo)
    _, images = runtime.stack_and_images(rev)
    image = images["python"]
    probe = RobustnessProbe(runtime.workspace.repo, runtime.store, runtime.brain, image)
    route = runtime.config.routing.get(Tier.CODE)
    stack, _ = runtime.stack_and_images(rev)
    record: dict[str, Any] = {
        "started_at": datetime.now(UTC).isoformat(),
        "unbidden": unbidden_version(),
        "repo": str(runtime.workspace.repo),
        "rev": rev,
        "package": args.package,
        "exception": args.exception,
        "environment": {"image": image.tag, "python": stack.python.version if stack.python else None},
        "model": {"remote": route.model if route else None, "profile": runtime.workspace.mandate().models.profile},
        "prompt_sha256": load_prompt("robustness_tests").sha256,
    }

    def hits(output: str) -> list[dict[str, str]]:
        return [
            {"exception": c.exception, "frame": c.frame, "example": c.example[:200]}
            for c in parse_crashes(output, args.package)
        ]

    if args.direct:
        work = snapshot(runtime.workspace.repo, rev)
        try:
            link_dependencies(work, image)
            script = "\n".join(
                ["import traceback", "try:", f"    {args.direct}", "    print('NO CRASH')", "except Exception:",
                 "    traceback.print_exc()", ""]
            )  # fmt: skip
            (work / "unbidden_direct.py").write_text(script)
            result = SandboxRunner().run(sandbox_spec(image, ["python", "unbidden_direct.py"], timeout_s=120), work)
        finally:
            discard(work)
        out = (result.stdout + result.stderr).strip()
        record["direct"] = {"statement": args.direct, "crashed": args.exception in out, "output": out[-800:]}
        print("direct:", record["direct"]["crashed"], out.splitlines()[-1:] if out else "")

    if args.replay:
        tests = Path(args.replay).read_text()
        rows = []
        for seed in range(args.seeds):
            output = probe.run_tests(rev, tests, seed=seed)
            found = hits(output)
            hit = any(h["exception"] == args.exception for h in found)
            rows.append({"seed": seed, "tests_sha256": _sha(tests), "found": hit, "crashes": found})
            print(f"replay seed {seed}: {'found' if rows[-1]['found'] else 'not found'}")
        record["replay"] = {"tests": args.replay, "runs": rows, "found": sum(r["found"] for r in rows)}

    async def fresh() -> list[dict[str, Any]]:
        rows = []
        for i in range(args.fresh):
            tests = await probe.write_tests(rev, args.package)
            if tests is None:
                rows.append({"run": i, "seed": 0, "tests_sha256": None, "found": False, "ran": False, "crashes": []})
                print(f"fresh {i}: no usable tests")
                continue
            output = await asyncio.to_thread(probe.run_tests, rev, tests, seed=0)
            found = hits(output)
            summary = next((ln for ln in reversed(output.splitlines()) if " passed" in ln or " failed" in ln), None)
            rows.append({"run": i, "seed": 0, "tests_sha256": _sha(tests), "ran": summary is not None,
                         "summary": summary, "found": any(h["exception"] == args.exception for h in found),
                         "crashes": found, "tests": tests})  # fmt: skip
            print(
                f"fresh {i}: {summary} -> {'found' if rows[-1]['found'] else 'not found'} {[h['frame'] for h in found]}"
            )
        return rows

    if args.fresh:
        rows = asyncio.run(fresh())
        record["fresh"] = {"runs": rows, "found": sum(r["found"] for r in rows), "ran": sum(r["ran"] for r in rows)}
    from unbidden.brain.spend import SpendLedger, summarize

    record["spend"] = summarize(SpendLedger().rows(run=os.environ["UNBIDDEN_RUN"]), "model")
    record["finished_at"] = datetime.now(UTC).isoformat()
    Path(f"{args.out}.json").write_text(json.dumps(record, indent=2) + "\n")
    print(Path(f"{args.out}.json"))


if __name__ == "__main__":
    main()
