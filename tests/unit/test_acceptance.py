"""Acceptance inside the product (stage 7): fixed conditions, judged by Unbidden's code, the model's claim apart."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_page_goal_answers import FIXED, PAGE, WANT, Brain, FakeScan, _repo
from unbidden.contracts.acceptance import Acceptance
from unbidden.contracts.common import utc_now
from unbidden.contracts.guardian import Goal, Mandate
from unbidden.director import acceptance as accept
from unbidden.director import presentation
from unbidden.director.goals import GoalRun
from unbidden.store import Store

pytestmark = pytest.mark.unit
FLAG = {"text_contains": "SHORT", "background": "red"}
OK_CHECKS = {"ok": True, "log": "ran 2 tests"}
TODAY = f"{utc_now():%Y-%m-%d}"  # the window changes are counted in


def fixed(mandate: Mandate) -> Acceptance:
    page = {**PAGE, "lines": ["Restock board", "B01", "Ask the floor lead"]}
    return accept.fix("page:g:r", presentation.conditions(WANT, FLAG, page, mandate))


def after(**extra: Any) -> dict[str, Any]:
    return {**FIXED, "lines": ["Restock board", "Ask the floor lead"], **extra}


def test_every_condition_holds_and_the_model_agrees_accepted(mandate: Mandate) -> None:
    acc = accept.judge(fixed(mandate), {"checks": OK_CHECKS, "page": after()}, "c1", "resolved")
    assert acc.state == "accepted" and {o.status for o in acc.outcomes} == {"satisfied"}


def test_the_model_says_fixed_and_a_check_fails_rejected(mandate: Mandate) -> None:
    acc = accept.judge(fixed(mandate), {"checks": OK_CHECKS, "page": PAGE | {"lines": after()["lines"]}}, "c1",
                       "resolved")  # fmt: skip
    assert acc.state == "rejected" and "marks" in acc.why  # B01 has no red SHORT mark: the claim does not count


def test_a_check_that_cannot_run_is_inconclusive_never_accepted(mandate: Mandate) -> None:
    acc = accept.judge(fixed(mandate), {"checks": {"ok": False, "ran": False, "log": "no checks declared"},
                                        "page": after()}, "c1", "resolved")  # fmt: skip
    assert acc.state == "inconclusive" and "checks" in acc.why
    unseen = accept.judge(fixed(mandate), {"checks": OK_CHECKS, "page": None}, "c1", "resolved")
    assert unseen.state == "inconclusive"


def test_a_change_that_meets_one_condition_and_breaks_another_is_rejected(mandate: Mandate) -> None:
    lost_row = after(rows=[FIXED["rows"][0]])  # B01 now marked, B02 gone from the page
    acc = accept.judge(fixed(mandate), {"checks": OK_CHECKS, "page": lost_row}, "c1", "resolved")
    by = {o.condition: o.status for o in acc.outcomes}
    assert acc.state == "rejected" and by["marks"] == "satisfied" and by["rows"] == "failed"
    hidden_help = after(lines=["Restock board"])
    assert accept.judge(fixed(mandate), {"checks": OK_CHECKS, "page": hidden_help}, "c1", "resolved").state == (
        "rejected"
    )


def test_an_unusable_model_observation_leaves_it_inconclusive(mandate: Mandate) -> None:
    acc = accept.judge(fixed(mandate), {"checks": OK_CHECKS, "page": after()}, "c1", "unusable")
    assert acc.state == "inconclusive"


def test_conditions_cannot_be_weakened_after_a_change_fails(mandate: Mandate) -> None:
    acc = accept.judge(fixed(mandate), {"checks": OK_CHECKS, "page": PAGE | {"lines": after()["lines"]}}, "c1",
                       "resolved")  # fmt: skip
    assert acc.state == "rejected"
    acc.conditions = [c for c in acc.conditions if c.id != "marks"]  # dropping the one that failed
    with pytest.raises(accept.ConditionsChanged):
        accept.judge(acc, {"checks": OK_CHECKS, "page": PAGE}, "c1", "resolved")


def test_an_accepted_result_goes_stale_when_another_commit_is_deployed(store: Store, mandate: Mandate) -> None:
    acc = accept.judge(fixed(mandate), {"checks": OK_CHECKS, "page": after()}, "c1", "resolved")
    store.put(accept.COLLECTION, acc)
    assert accept.refresh(store, "page:g:", "c1") == []
    (stale,) = accept.refresh(store, "page:g:", "c2")
    assert stale.state == "stale" and "c2" in stale.why


def test_through_the_page_goal_a_fix_the_checks_reject_is_withdrawn(
    store: Store, mandate: Mandate, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit.test_page_goal_answers import ONE

    repo, deploys = _repo(tmp_path), []

    async def propose(*_: Any) -> tuple[dict[str, str], str, dict[str, Any]]:
        return {"board.css": ".short { background: pink; }\n"}, "made it pink", {}

    def deploy(repo: Path, store: Any, mandate: Any, commit: str, *, reason: str, rollback: bool = False) -> Any:
        deploys.append(rollback)
        return type("D", (), {"ok": True, "log": ""})()

    # The page after the change still has no red SHORT mark; the model says it is fine.
    monkeypatch.setattr("unbidden.lab.ui.scan", lambda url, out: FakeScan())
    monkeypatch.setattr(presentation, "propose", propose)
    monkeypatch.setattr(presentation, "run_checks", lambda tree, mandate: OK_CHECKS)
    monkeypatch.setattr("unbidden.operate.deploy.deploy", deploy)
    run = GoalRun(goal="g")
    asyncio.run(presentation.pursue_page(Brain(ONE, '{"discrepancies": [], "cause": "none"}'), store, mandate,
                                         Goal(id="g", statement="s", bounds={"max_changes": 1}), run, WANT, "u",
                                         repo=repo, artifacts=tmp_path / "a", perception="dom", window=TODAY,
                                         source="synthetic"))  # fmt: skip
    assert run.status == "page_unresolved" and deploys == [False, True]
    (acc,) = store.list(accept.COLLECTION, Acceptance)
    assert acc.state == "rejected" and acc.model_claim == "resolved"


def test_an_ambiguous_goal_changes_nothing_and_asks(
    store: Store, mandate: Mandate, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("unbidden.lab.ui.scan", lambda url, out: FakeScan())
    no_flag = '{"discrepancies": [{"key": "B01", "kind": "not_flagged", "evidence": "x"}], "cause": "c", "flag": null}'
    run = GoalRun(goal="g")
    asyncio.run(presentation.pursue_page(Brain(no_flag), store, mandate,
                                         Goal(id="g", statement="s", bounds={"max_changes": 1}), run, WANT, "u",
                                         repo=tmp_path, artifacts=tmp_path, perception="dom", window="w",
                                         source="synthetic"))  # fmt: skip
    assert run.status == "page_needs_clarification" and store.list(accept.COLLECTION, Acceptance) == []


def test_activity_keeps_the_four_parts_apart(store: Store, mandate: Mandate) -> None:
    from unbidden.director.activity import (
        _ecosystem,  # pyright: ignore[reportPrivateUsage]
        build,
        render_text,
    )

    acc = accept.judge(fixed(mandate), {"checks": OK_CHECKS, "page": PAGE | {"lines": after()["lines"]}}, "c1",
                       "resolved")  # fmt: skip
    acc.change = {"commit": "c1abcdef0123"}
    store.put(accept.COLLECTION, acc)
    (shown,) = _ecosystem(store)["acceptances"]
    assert shown["applied"] == "c1abcdef0123" and shown["model_claim"] == "resolved" and shown["state"] == "rejected"
    assert "marks" in shown["checks"]["failed"]
    data = build(store, "w", spend_rows=[])
    line = next(t for t in render_text(data) if t.startswith("[bold]change[/]"))
    assert "model says resolved" in line and "failed ['marks']" in line and "rejected" in line
