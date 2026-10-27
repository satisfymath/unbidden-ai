"""How demanding each kind of model call is. Heavy work is worth a frontier model when the content may leave."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from unbidden.contracts.llm import Source

Weight = Literal["light", "heavy"]


@dataclass(frozen=True)
class TaskSpec:
    weight: Weight
    escalate: bool = True  # may another route be tried when the first one fails
    local_only: bool = False  # never leaves, whatever the profile (e.g. reviewing what is about to leave)


TASKS: dict[str, TaskSpec] = {
    # Classify, decide, pick among known names: local models do these well and fast.
    "world.endpoint_tables": TaskSpec("light", escalate=False),
    "bridge.names": TaskSpec("light", escalate=False, local_only=True),  # reads the private code to rename it
    "bridge.review": TaskSpec("light", escalate=False, local_only=True),  # looks for what still gives it away
    "research.step": TaskSpec("light"),
    # Write code, tests, workloads or parsers: where a frontier model earns its cost.
    "lab.fix_candidate": TaskSpec("heavy"),
    "lab.perf_candidate": TaskSpec("heavy"),
    "lab.workload": TaskSpec("heavy"),
    "lab.robust_fix": TaskSpec("heavy"),
    "research.robustness": TaskSpec("heavy"),
    "forge.tests": TaskSpec("light"),
    "forge.adapter": TaskSpec("heavy"),
    "forge.adapter.bridge": TaskSpec("heavy", escalate=False),
    "forge.stats": TaskSpec("heavy", escalate=False),
    "forge.stats.bridge": TaskSpec("heavy", escalate=False),
    "bridge.solve": TaskSpec("heavy", escalate=False),
}


def task_for(purpose: str) -> TaskSpec:
    """Unknown purposes are light and local: a new call never reaches a remote model by accident."""
    return TASKS.get(purpose, TaskSpec("light", escalate=False))


# Where each task's content usually comes from, for `unbidden route --explain` (the router classifies the real one).
TYPICAL_SOURCES: dict[str, tuple[Source, ...]] = {
    "world.endpoint_tables": ("repo",),
    "bridge.names": ("repo",),
    "research.step": ("repo", "runtime"),
    "lab.fix_candidate": ("repo",),
    "lab.perf_candidate": ("repo",),
    "lab.workload": ("repo",),
    "lab.robust_fix": ("repo",),
    "research.robustness": ("repo",),
    "forge.tests": ("runtime",),
    "forge.adapter": ("runtime",),
    "forge.adapter.bridge": ("synthetic",),
    "forge.stats": ("runtime",),
    "forge.stats.bridge": ("synthetic",),
    "bridge.solve": ("synthetic",),
}
