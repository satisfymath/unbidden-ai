"""What the lab's own history says about the chance an experiment succeeds, per kind of opportunity.

A Beta-binomial per (source, category, language): the prior is the constant the Director used before (0.6, worth
two experiments), updated by every experiment Unbidden ran. A success is an improvement the team's suite validated;
a failure is an experiment that found no proven fix. Few outcomes leave the prior nearly as it was; a kind that has
failed ten times in a row stops looking like a good bet. Nothing here calls a model or leaves the machine.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from unbidden.contracts.experiment import VALIDATING
from unbidden.contracts.opportunity import Opportunity
from unbidden.languages import adapter_for_path
from unbidden.store import Store

PRIOR_MEAN, PRIOR_WEIGHT = 0.6, 2.0


@dataclass(frozen=True)
class Belief:
    successes: int
    failures: int

    @property
    def mean(self) -> float:
        alpha, beta = PRIOR_MEAN * PRIOR_WEIGHT, (1 - PRIOR_MEAN) * PRIOR_WEIGHT
        return (alpha + self.successes) / (alpha + beta + self.successes + self.failures)


def kind_of(opp: Opportunity) -> tuple[str, str, str]:
    paths = [str(p) for p in opp.details.get("paths") or []]
    language = adapter_for_path(paths[0]) if paths else None
    return opp.source.split(":")[0], opp.category, language.name if language else "-"


def _outcomes(details: dict[str, Any]) -> tuple[int, int]:
    verdicts = [*details.get("past_verdicts", []), *([details["verdict"]] if details.get("verdict") else [])]
    successes = sum(1 for v in verdicts if v.get("improved") is True and v.get("tests") in VALIDATING)
    failures = int(details.get("attempts", 0)) + int(details.get("attempts_total", 0))
    return successes, failures


def beliefs(store: Store) -> dict[tuple[str, str, str], Belief]:
    counts: dict[tuple[str, str, str], list[int]] = defaultdict(lambda: [0, 0])
    for opp in store.list("opportunities", Opportunity):
        s, f = _outcomes(opp.details)
        counts[kind_of(opp)][0] += s
        counts[kind_of(opp)][1] += f
    return {k: Belief(s, f) for k, (s, f) in counts.items()}
