"""E1: the Director's chance of success comes from the lab's history of the same kind of opportunity, and value from
the mandate's table, instead of constants."""

from __future__ import annotations

import pytest

from unbidden.contracts.common import EvidenceRef
from unbidden.contracts.guardian import Mandate
from unbidden.contracts.opportunity import ActionKind, Opportunity
from unbidden.director.decide import Context, decide
from unbidden.director.learn import PRIOR_MEAN, Belief, beliefs, kind_of
from unbidden.store import Store

pytestmark = pytest.mark.unit


def opp(source: str = "mypy", category: str = "types", path: str = "a.py", **details: object) -> Opportunity:
    return Opportunity(
        source=source, category=category, title="t", summary="s", dedup_key=f"{source}:{path}:{len(details)}",
        evidence=[EvidenceRef(kind="file", locator=path)], details={"paths": [path], **details},
    )  # fmt: skip


def test_without_history_the_prior_is_the_old_constant() -> None:
    assert Belief(0, 0).mean == pytest.approx(PRIOR_MEAN)


def test_history_moves_the_belief_and_little_history_moves_it_little() -> None:
    assert Belief(0, 1).mean == pytest.approx(1.2 / 3)
    assert Belief(0, 10).mean == pytest.approx(1.2 / 12)
    assert Belief(5, 0).mean > PRIOR_MEAN


def test_outcomes_are_counted_per_kind_from_the_store(store: Store) -> None:
    validated = {"improved": True, "tests": "passed"}
    store.put("opportunities", opp(attempts=1, attempts_total=2))
    store.put("opportunities", opp(path="b.py", verdict=validated))
    store.put("opportunities", opp(path="c.py", verdict={"improved": True, "tests": "regression"}))
    store.put("opportunities", opp(source="eslint", category="lint", path="x.ts", attempts=2))
    learned = beliefs(store)
    assert learned[("mypy", "types", "python")] == Belief(successes=1, failures=3)
    assert learned[("eslint", "lint", "node")] == Belief(successes=0, failures=2)


def test_a_kind_that_keeps_failing_is_no_longer_worth_an_experiment(mandate: Mandate) -> None:
    fresh = opp()
    assert decide(fresh, mandate, Context(0, 0)).chosen is ActionKind.RUN_EXPERIMENT
    hopeless = Context(0, 0, p_experiment=Belief(0, 60).mean)
    decision = decide(fresh, mandate, hopeless)
    assert decision.chosen is ActionKind.WAIT  # expected value below the experiment's cost


def test_the_mandate_states_what_a_category_is_worth(mandate: Mandate) -> None:
    assert decide(opp(category="docs"), mandate, Context(0, 0)).chosen is ActionKind.DECLINE
    mandate.evaluation.value_hours = {"docs": 0.8}
    assert decide(opp(category="docs"), mandate, Context(0, 0)).chosen is ActionKind.RUN_EXPERIMENT


def test_kinds_are_source_category_and_language() -> None:
    assert kind_of(opp(source="ruff:pkg")) == ("ruff", "types", "python")
    assert kind_of(opp(path="main.go")) == ("mypy", "types", "go")
