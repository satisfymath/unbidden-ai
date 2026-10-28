"""The evaluation corpus: a stratified, reproducible sample of public repositories, split once into dev, validation
and holdout.

    uv run python -m bench.corpus snapshot --out bench/corpus/2026-10-28-pool.json      # queries GitHub once
    uv run python -m bench.corpus sample bench/corpus/2026-10-28-pool.json --seed 20261028 \\
        --out bench/repos/corpus-2026-10-28.yaml                                            # deterministic

Reproducibility rests on the committed pool, not on GitHub: search ranking changes over time, so the pool fetched on
one day is saved with its queries, and sampling and splitting are a pure function of (pool, seed, allocation).

Strata are language x popularity bucket. Within each stratum candidates are filtered by fixed rules (OSI license,
not a fork, not archived, pushed in the last six months, under 500 MB, not a list or a course, never used while
developing Unbidden), shuffled by the seed, and the first n taken. Each chosen repository is then assigned to dev,
validation or holdout by its position in a second seeded shuffle of its stratum, so every split covers every stratum.
Commits are pinned to the default branch's HEAD on the snapshot day.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

# How many of the ~100 repositories each language gets. Weighted toward what Unbidden analyzes, with languages it does
# not analyze kept in the denominator: the corpus measures the product's reach, not only its depth.
ALLOCATION: dict[str, int] = {
    "Python": 30,
    "TypeScript": 18,
    "JavaScript": 12,
    "Go": 10,
    "Rust": 7,
    "Java": 7,
    "Ruby": 5,
    "PHP": 5,
    "C#": 3,
    "Kotlin": 3,
}
BUCKETS: dict[str, str] = {"small": "50..499", "medium": "500..4999", "large": ">=5000"}
SPLITS = (("dev", 0.4), ("validation", 0.3), ("holdout", 0.3))
OSI = {"MIT", "Apache-2.0", "BSD-3-Clause", "BSD-2-Clause", "ISC", "MPL-2.0", "GPL-3.0", "GPL-2.0", "LGPL-3.0",
       "LGPL-2.1", "AGPL-3.0", "Unlicense", "0BSD", "EPL-2.0", "Zlib", "BSL-1.0", "CC0-1.0"}  # fmt: skip
NOT_SOFTWARE = re.compile(r"awesome|tutorial|course|interview|roadmap|cheatsheet|leetcode|examples?$|-list$|books?",
                          re.IGNORECASE)  # fmt: skip
MAX_SIZE_KB = 500_000

# Every repository Unbidden met while being developed, from every manifest and decision record.
USED = {
    "satisfymath/full-stack-fastapi-template", "fastapi/full-stack-fastapi-template", "textualize/rich",
    "mealie-recipes/mealie", "open-telemetry/opentelemetry-demo", "facebook/lexical", "facebook/docusaurus",
    "saleor/saleor", "chatwoot/chatwoot", "immich-app/immich", "pallets/click", "encode/httpx", "fastify/fastify",
    "fastapi/sqlmodel", "honojs/hono", "simonw/llm", "meta-llama/llama-cookbook", "meta-llama/llama-stack",
    "meta-llama/llama-stack-client-python", "meta-llama/llama-stack-client-typescript", "ogx-ai/ogx",
    "ogx-ai/ogx-client-python", "ogx-ai/ogx-client-typescript", "apache/burr", "apache/hamilton", "fastapi/typer",
    "pydantic/logfire", "guardrails-ai/guardrails", "kaiko-ai/eva",
}  # fmt: skip


def _used_from_manifests(root: Path) -> set[str]:
    found = set(USED)
    for path in sorted((root / "bench" / "repos").glob("*.yaml")):
        for repo in (yaml.safe_load(path.read_text()) or {}).get("repos", []):
            found.add(repo["url"].removeprefix("https://github.com/").lower())
    return {f.lower() for f in found}


def snapshot(token: str, *, per_stratum: int, day: datetime) -> dict[str, Any]:
    """Query GitHub once per stratum and keep every candidate with the fields the filters read."""
    import httpx

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    pushed = (day - timedelta(days=183)).date().isoformat()
    strata: dict[str, Any] = {}
    for language in ALLOCATION:
        for bucket, stars in BUCKETS.items():
            query = f"language:{json.dumps(language) if ' ' in language else language} stars:{stars} " \
                    f"pushed:>{pushed} archived:false fork:false is:public"  # fmt: skip
            items: list[dict[str, Any]] = []
            for page in range(1, per_stratum // 100 + 1):
                response = httpx.get(
                    "https://api.github.com/search/repositories",
                    params={"q": query, "sort": "updated", "order": "desc", "per_page": 100, "page": page},
                    headers=headers,
                    timeout=60,
                )
                response.raise_for_status()
                items += response.json().get("items", [])
                time.sleep(2.5)  # search allows 30 requests a minute
            strata[f"{language}/{bucket}"] = {
                "query": query,
                "candidates": [
                    {
                        k: i.get(k)
                        for k in (
                            "full_name",
                            "html_url",
                            "default_branch",
                            "stargazers_count",
                            "size",
                            "pushed_at",
                            "archived",
                            "fork",
                            "topics",
                            "description",
                        )
                    }
                    | {"license": (i.get("license") or {}).get("spdx_id"), "language": i.get("language")}
                    for i in items
                ],
            }
            print(f"{language}/{bucket}: {len(items)} candidates", flush=True)
    return {"taken_at": day.isoformat(), "pushed_after": pushed, "per_stratum": per_stratum, "strata": strata}


def eligible(candidate: dict[str, Any], used: set[str]) -> str | None:
    """Why a candidate is excluded, or None. Fixed rules, applied to every stratum alike."""
    name = str(candidate["full_name"])
    if name.lower() in used:
        return "used while developing Unbidden"
    if candidate.get("fork") or candidate.get("archived"):
        return "fork or archived"
    if candidate.get("license") not in OSI:
        return f"license {candidate.get('license')!r} is not an OSI license we accept"
    if (candidate.get("size") or 0) > MAX_SIZE_KB:
        return "over 500 MB"
    if NOT_SOFTWARE.search(name.split("/")[1]) or NOT_SOFTWARE.search(str(candidate.get("description") or "")[:80]):
        return "a list, course or collection rather than software"
    return None


def _quota(language: str) -> dict[str, int]:
    """A language's repositories spread over the buckets as evenly as possible (small first)."""
    n = ALLOCATION[language]
    base, extra = divmod(n, len(BUCKETS))
    return {b: base + (1 if i < extra else 0) for i, b in enumerate(BUCKETS)}


def split_counts(n: int) -> dict[str, int]:
    """dev / validation / holdout sizes for n repositories, by largest remainder (3 -> 1/1/1, 30 -> 12/9/9)."""
    exact = {name: n * part for name, part in SPLITS}
    counts = {name: int(v) for name, v in exact.items()}
    for name in sorted(exact, key=lambda k: (-(exact[k] - counts[k]), [s for s, _ in SPLITS].index(k))):
        if sum(counts.values()) >= n:
            break
        counts[name] += 1
    return counts


def sample(pool: dict[str, Any], seed: int, used: set[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Pick each stratum's quota from its eligible candidates, then split each language's picks by a seeded shuffle,
    so every language is present in every split."""
    chosen: list[dict[str, Any]] = []
    excluded: dict[str, dict[str, int]] = {}
    seen: set[str] = set()
    for language in ALLOCATION:
        picks: list[dict[str, Any]] = []
        for bucket, n in _quota(language).items():
            key = f"{language}/{bucket}"
            candidates = sorted(pool["strata"][key]["candidates"], key=lambda c: c["full_name"].lower())
            reasons: dict[str, int] = {}
            kept = []
            for c in candidates:
                why = eligible(c, used) or ("duplicate" if c["full_name"].lower() in seen else None)
                if why:
                    reasons[why] = reasons.get(why, 0) + 1
                else:
                    kept.append(c)
            excluded[key] = reasons
            random.Random(f"{seed}:{key}").shuffle(kept)
            for c in kept[:n]:
                seen.add(c["full_name"].lower())
                picks.append({"stratum": key, **c})
        random.Random(f"{seed}:{language}:split").shuffle(picks)
        labels = [name for name, count in split_counts(len(picks)).items() for _ in range(count)]
        chosen += [{"split": label, **c} for label, c in zip(labels, picks, strict=True)]
    return chosen, excluded


def pin(repo: dict[str, Any]) -> str | None:
    out = subprocess.run(
        ["git", "ls-remote", repo["html_url"], f"refs/heads/{repo['default_branch']}"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return out.stdout.split()[0] if out.returncode == 0 and out.stdout.strip() else None


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    snap = sub.add_parser("snapshot")
    snap.add_argument("--out", required=True)
    snap.add_argument("--per-stratum", type=int, default=100)
    samp = sub.add_parser("sample")
    samp.add_argument("pool")
    samp.add_argument("--seed", type=int, required=True)
    samp.add_argument("--out", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.command == "snapshot":
        env = dict(
            line.split("=", 1) for line in (Path.home() / ".unbidden" / ".env").read_text().splitlines() if "=" in line
        )
        data = snapshot(env["GITHUB_TOKEN"].strip(), per_stratum=args.per_stratum, day=datetime.now(UTC))
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(data, indent=1) + "\n")
        return
    pool = json.loads(Path(args.pool).read_text())
    chosen, excluded = sample(pool, args.seed, _used_from_manifests(root))
    repos = []
    for c in chosen:
        commit = pin(c)
        name = c["full_name"].replace("/", "__")
        repos.append(
            {"name": name, "url": c["html_url"], "commit": commit, "split": c["split"], "stratum": c["stratum"],
             "language": c["language"], "stars": c["stargazers_count"], "size_kb": c["size"], "license": c["license"],
             "default_branch": c["default_branch"]}
        )  # fmt: skip
        print(f"{c['split']:10} {c['stratum']:22} {c['full_name']} {commit and commit[:12]}", flush=True)
    digest = hashlib.sha256(Path(args.pool).read_bytes()).hexdigest()
    header = {
        "pool": args.pool,
        "pool_sha256": digest,
        "seed": args.seed,
        "allocation": ALLOCATION,
        "buckets": BUCKETS,
        "splits": dict(SPLITS),
        "excluded_by_rule": excluded,
        "pinned_at": datetime.now(UTC).isoformat(),
    }
    Path(args.out).write_text(yaml.safe_dump({"corpus": header, "repos": repos}, sort_keys=False, width=200))


if __name__ == "__main__":
    main()
