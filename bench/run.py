"""Model benchmark: each cell (tier, provider, model, think) runs every task through the real Brain path.

Usage: uv run python -m bench.run [--reps 3] [--cells local,spark13,wonder] [--out docs/bench/<name>.md]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from bench.tasks import TASKS, Task
from unbidden.brain.providers import LLMProvider, ProviderError
from unbidden.brain.providers.ollama import OllamaProvider
from unbidden.brain.providers.openai_compat import OpenAICompatProvider
from unbidden.brain.router import Brain, BrainError
from unbidden.config import Route, load_config
from unbidden.contracts.guardian import (
    Autonomy,
    AutonomyPolicy,
    BusinessConstraints,
    EgressPolicy,
    Mandate,
    RemoteModelPolicy,
)
from unbidden.contracts.llm import ModelRun, Tier
from unbidden.store import Store


@dataclass(frozen=True)
class Cell:
    label: str
    tier: Tier
    provider: str
    model: str
    think: str | None


CELLS = {
    "local": Cell("glimmer-30b-mlx", Tier.LOCAL, "ollama", "muse-glimmer:30b-mlx", "low"),
    "local_off": Cell("glimmer-30b-mlx think=off", Tier.LOCAL, "ollama", "muse-glimmer:30b-mlx", "off"),
    "spark13": Cell("muse-spark-1.3", Tier.FRONTIER, "meta", "muse-spark-1.3", "low"),
    "spark13_none": Cell("muse-spark-1.3 no effort", Tier.FRONTIER, "meta", "muse-spark-1.3", None),
    "spark12": Cell("muse-spark-1.2", Tier.FRONTIER, "meta", "muse-spark-1.2", "low"),
    "wonder": Cell("muse-wonder-1.0", Tier.FRONTIER, "meta", "muse-wonder-1.0", None),
}


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip())


def _mandate() -> Mandate:
    return Mandate(
        workspace="bench",
        autonomy=AutonomyPolicy(run_experiments=Autonomy.ALLOW, delegate_synthetic=Autonomy.ALLOW),
        business_constraints=BusinessConstraints(maximum_monthly_spend_usd=5.0),
        egress=EgressPolicy(remote_models=RemoteModelPolicy(destinations=["api.meta.ai"])),
    )


@dataclass
class Result:
    cell: str
    task: str
    first_try: bool
    valid: bool
    correct: bool
    problem: str | None
    seconds: float
    tokens_out: int
    usd: float


async def run_one(brain: Brain, store: Store, cell: Cell, task: Task, rep: int) -> Result:
    before = {r.id for r in store.list("model_runs", ModelRun)}
    request = task.request(cell.tier).model_copy(update={"correlation_id": f"{cell.label}/{task.name}/{rep}"})
    started = time.monotonic()
    valid, problem, correct = False, None, False
    try:
        response = await brain.complete(request)
        valid = True
        problem = task.check(response)
        correct = problem is None
    except (BrainError, ProviderError) as exc:
        problem = f"{type(exc).__name__}: {exc}"[:300]
    except Exception as exc:  # a semantic check that crashes on a malformed but schema-valid answer
        problem = f"check crashed: {type(exc).__name__}: {exc}"[:300]
    elapsed = time.monotonic() - started
    runs = [r for r in store.list("model_runs", ModelRun) if r.id not in before]
    return Result(
        cell=cell.label,
        task=task.name,
        first_try=bool(runs) and runs[0].ok,
        valid=valid,
        correct=correct,
        problem=problem,
        seconds=elapsed,
        tokens_out=sum(r.cost.tokens_out for r in runs),
        usd=sum(r.cost.usd for r in runs),
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--cells", default="local,spark13,wonder")
    parser.add_argument("--out", type=Path, default=Path(f"docs/bench/{date.today()}-models.md"))
    args = parser.parse_args()
    _load_env(Path(".env"))

    config = load_config()
    providers: dict[str, LLMProvider] = {
        "ollama": OllamaProvider(config.providers["ollama"].base_url),
        "meta": OpenAICompatProvider(
            "meta", config.providers["meta"].base_url, "MODEL_API_KEY", required_tool_choice=False
        ),
    }
    store = Store(Path(".unbidden/bench.db"))
    results: list[Result] = []
    for key in args.cells.split(","):
        cell = CELLS[key]
        config.routing[cell.tier] = Route(
            provider=cell.provider,
            model=cell.model,
            think=cell.think,
            think_schema_only=cell.think,
            think_budget=1024 if cell.think not in (None, "off") else 0,
        )
        brain = Brain(config, providers, store, _mandate())
        for task in TASKS:
            if task.local_only and cell.tier.remote:
                continue
            for rep in range(args.reps):
                result = await run_one(brain, store, cell, task, rep)
                results.append(result)
                mark = "ok " if result.correct else "BAD"
                print(f"{mark} {cell.label:28} {task.name:18} {result.seconds:6.1f}s  {result.problem or ''}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.with_suffix(".json").write_text(json.dumps([r.__dict__ for r in results], indent=2))
    args.out.write_text(render(results, args.reps))
    print(f"\nwrote {args.out}")


def render(results: list[Result], reps: int) -> str:
    lines = [
        f"# Model benchmark, {date.today()}",
        "",
        f"Each task ran {reps} times per cell through `Brain.complete` (validation and one repair included).",
        "Valid: the answer met its contract. Correct: it also passed the task's semantic check.",
        "Tasks marked local-only hold private names and never run on a remote tier.",
        "",
        "| Cell | Task | First try valid | Valid | Correct | Median s | Tokens out | US$ |",
        "|---|---|---|---|---|---|---|---|",
    ]
    keys = list(dict.fromkeys((r.cell, r.task) for r in results))
    for cell, task in keys:
        rows = [r for r in results if r.cell == cell and r.task == task]
        n = len(rows)
        lines.append(
            f"| {cell} | {task} | {sum(r.first_try for r in rows)}/{n} | {sum(r.valid for r in rows)}/{n} | "
            f"{sum(r.correct for r in rows)}/{n} | {statistics.median(r.seconds for r in rows):.1f} | "
            f"{statistics.median(r.tokens_out for r in rows):.0f} | {sum(r.usd for r in rows):.4f} |"
        )
    lines += ["", "## Totals per cell", "", "| Cell | Correct | Median s per call | US$ |", "|---|---|---|---|"]
    for cell in dict.fromkeys(r.cell for r in results):
        rows = [r for r in results if r.cell == cell]
        lines.append(
            f"| {cell} | {sum(r.correct for r in rows)}/{len(rows)} | "
            f"{statistics.median(r.seconds for r in rows):.1f} | {sum(r.usd for r in rows):.4f} |"
        )
    failures = [r for r in results if not r.correct]
    if failures:
        lines += ["", "## Failures", ""]
        lines += [f"- {r.cell} / {r.task}: {r.problem}" for r in failures]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    asyncio.run(main())
