"""The inputs every policy decides alike (Director only, evaluator only, world checks), with their truth.

    uv run python -m bench.eval2.cases <out dir> [--opportunities <frozen scan opportunities.json>]

Writes `<out>/cases.json` (what policies see) and `<out>/oracle/cases.json` (acceptable outcomes, read only by the
scorer). Planted-repository opportunities come from one scan by the current scanner, frozen to a file, so every
policy decides the same input. Deterministic.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any

MANDATE: dict[str, Any] = {
    "workspace": "eval2",
    "priorities": ["correctness"],
    "autonomy": {
        "observe": "allow",
        "run_experiments": "allow",
        "provision_dependencies": "allow",
        "open_pull_requests": "require_approval",
        "use_new_capabilities": "require_approval",
    },
}
REF = [{"kind": "config", "locator": "psql"}]


def _opportunity(title: str, details: dict[str, Any], *, category: str = "performance") -> dict[str, Any]:
    return {
        "source": "world",
        "category": category,
        "title": title,
        "summary": title,
        "dedup_key": title,
        "evidence": REF,
        "details": details,
    }


def _world(rows: int) -> dict[str, Any]:
    def resource(rid: str, kind: str, name: str, attributes: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": rid,
            "kind": kind,
            "name": name,
            "attributes": attributes,
            "status": "observed",
            "confidence": 1.0,
            "evidence": REF,
        }

    return {
        "rev": "a" * 40,
        "resources": {
            "table:orders": resource("table:orders", "table", "orders", {"indexes": [], "rows_estimate": rows}),
            "table:customers": resource("table:customers", "table", "customers", {"indexes": []}),
            "endpoint:GET /orders": resource("endpoint:GET /orders", "endpoint", "GET /orders", {}),
        },
        "relations": [
            {
                "src": "table:orders",
                "dst": "table:customers",
                "predicate": "references",
                "status": "observed",
                "confidence": 1.0,
                "evidence": [{"kind": "config", "locator": "psql", "note": "orders.customer_id -> customers"}],
            },
            {
                "src": "endpoint:GET /orders",
                "dst": "table:orders",
                "predicate": "reads",
                "status": "inferred",
                "confidence": 0.6,
                "evidence": REF,
            },
        ],
    }


def _summary(rounds: list[list[str]], collected: int | None = 12) -> dict[str, Any]:
    if collected is None:  # recorded before round statuses existed: the suite never reported
        return {"rounds": len(rounds), "failed_per_round": rounds}
    return {
        "rounds": len(rounds),
        "failed_per_round": rounds,
        "round_status": ["ran"] * len(rounds),
        "collected_per_round": [collected] * len(rounds),
    }


def synthetic() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rng = random.Random(20261028)
    faster = [rng.gauss(100, 5) for _ in range(20)], [rng.gauss(50, 3) for _ in range(20)]
    same = [rng.gauss(100, 5) for _ in range(20)], [rng.gauss(100, 5) for _ in range(20)]
    cases: list[dict[str, Any]] = [
        {
            "id": "unmeasured-fk",
            "kind": "decide",
            "mandate": MANDATE,
            "context": {"open_pull_requests": 0, "attempts": 0},
            "opportunity": _opportunity(
                "orders.customer_id is a foreign key without an index, filtered by 1 endpoint(s)",
                {
                    "check": "unindexed_foreign_key",
                    "table": "orders",
                    "column": "customer_id",
                    "cost_path": "filter",
                    "rows": None,
                    "endpoints": ["GET /orders"],
                },
            ),
        },
        {
            "id": "unread-logs",
            "kind": "decide",
            "mandate": MANDATE,
            "context": {"open_pull_requests": 0, "attempts": 0, "capability_needs": {"compose:api": "open"}},
            "opportunity": _opportunity(
                "GET /orders is slow under Unbidden's probes",
                {"check": "slow_endpoint", "endpoints": ["GET /orders"], "service": "api", "traffic": "unknown"},
            ),
        },
        {
            "id": "data-growth",
            "kind": "world",
            "steps": [{"world": _world(10_000), "then": "decline"}, {"world": _world(30_000)}],
        },
        {
            "id": "flaky-candidate",
            "kind": "judge",
            "before_ms": faster[0],
            "after_ms": faster[1],
            "baseline_tests": _summary([[], [], []]),
            "candidate_tests": _summary([["t::x"], [], ["t::x"]]),
        },
        {
            "id": "noise-improvement",
            "kind": "judge",
            "before_ms": same[0],
            "after_ms": same[1],
            "baseline_tests": _summary([[], [], []]),
            "candidate_tests": _summary([[], [], []]),
        },
        {
            "id": "suite-never-ran",
            "kind": "judge",
            "before_ms": faster[0],
            "after_ms": faster[1],
            "baseline_tests": _summary([["<suite>"]] * 3, None),
            "candidate_tests": _summary([["<suite>"]] * 3, None),
        },
    ]
    oracle = {
        "unmeasured-fk": {
            "kind": "needs_measurement",
            "acceptable": ["measure", "investigate", "wait"],
            "why": "its value depends on rows nobody has observed; measuring is cheap, an experiment is not",
        },
        "unread-logs": {
            "kind": "missing_capability",
            "acceptable": ["acquire_capability", "wait"],
            "why": "whether users call the endpoint is in an access log no reader parses yet",
        },
        "data-growth": {
            "kind": "data_change",
            "acceptable_final": "open",
            "why": "the table tripled since the decline, at the same commit",
        },
        "flaky-candidate": {"kind": "apparent_improvement", "max_level": 3},
        "noise-improvement": {"kind": "apparent_improvement", "max_level": 2},
        "suite-never-ran": {"kind": "apparent_improvement", "max_level": 3},
    }
    return cases, oracle


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("--opportunities", help="frozen opportunities of the planted repositories, by scenario")
    args = parser.parse_args()
    out = Path(args.out).expanduser()
    cases, oracle = synthetic()
    if args.opportunities:
        planted: dict[str, list[dict[str, Any]]] = json.loads(Path(args.opportunities).read_text())
        for scenario, opps in sorted(planted.items()):
            for opp in opps:
                cases.append(
                    {
                        "id": f"{scenario}/{opp['id']}",
                        "kind": "decide",
                        "mandate": MANDATE,
                        "context": {"open_pull_requests": 0, "attempts": 0},
                        "opportunity": opp,
                    }
                )
    (out / "oracle").mkdir(parents=True, exist_ok=True)
    (out / "cases.json").write_text(json.dumps(cases, indent=1))
    (out / "oracle" / "cases.json").write_text(json.dumps(oracle, indent=1))
    print(json.dumps({"cases": len(cases)}))


if __name__ == "__main__":
    main()
