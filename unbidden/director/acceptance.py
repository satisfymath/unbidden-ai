"""Acceptance of a change: conditions fixed before it, evaluated by Unbidden's own code on what is deployed after it.

Reusable kinds, each evaluated without a model:
- `checks_pass`: the application's declared checks passed on the changed tree;
- `keys_once`: every key of the data still appears on exactly one row of the page (nothing hidden or duplicated);
- `information_kept`: what a person read on the page besides the rows is still there (digits may change);
- `marks`: rows that must be flagged carry a visible mark with the given text and background colour, and no other
  row carries one (the text and colour come from the goal and the project, proposed before any change);
- `action_effect`: an action's documented effect was read back (`operate/actions.py` verification).

A condition that cannot be evaluated (no observation for it) is `unverifiable` and leaves the result inconclusive,
never accepted. The model's claim ("resolved") is kept beside the outcomes: it is required, never sufficient. The
conditions are sealed when fixed; evaluating conditions that no longer match their seal is refused, so they cannot
be weakened after a change fails. An acceptance observed on one deployed commit is stale once another is deployed.
"""

from __future__ import annotations

import re
from typing import Any

from unbidden.contracts.acceptance import Acceptance, Condition, Outcome
from unbidden.store import Store

COLLECTION = "acceptances"


class ConditionsChanged(RuntimeError):
    """The conditions of an acceptance differ from what was fixed before the change."""


def fix(subject: str, conditions: list[Condition]) -> Acceptance:
    return Acceptance(subject=subject, conditions=conditions, sealed=Acceptance.seal(conditions))


def info_lines(lines: list[str], keys: set[str]) -> set[str]:
    return {re.sub(r"\d+", "#", line) for line in lines if line and not any(k in line for k in keys)}


def _rows_of(page: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return [r for r in page.get("rows", []) if key in r.get("cells", [])]


def _marked(row: dict[str, Any], spec: dict[str, Any]) -> bool:
    from unbidden.director.presentation import colour_name

    text, colour, least = str(spec["text_contains"]), str(spec["background"]), float(spec.get("min_visible", 0.9))
    return any(
        text.lower() in str(m.get("text", "")).lower()
        and colour_name(str(m.get("background", ""))) == colour
        and (m.get("visible") or 0) >= least
        and m.get("visibility", "visible") == "visible"
        for m in row.get("marks", [])
    )


def evaluate(condition: Condition, evidence: dict[str, Any], basis: str) -> Outcome:
    """One condition against what was observed. Missing evidence: unverifiable."""
    spec, kind = condition.spec, condition.kind

    def out(ok: bool | None, observation: dict[str, Any]) -> Outcome:
        status = "unverifiable" if ok is None else "satisfied" if ok else "failed"
        return Outcome(condition=condition.id, status=status, observation=observation, basis=basis)

    if kind == "checks_pass":
        checks = evidence.get("checks")
        if not checks or checks.get("ran") is False:
            return out(None, {"why": (checks or {}).get("log", "no checks ran")[-300:]})
        return out(bool(checks.get("ok")), {"log": str(checks.get("log", ""))[-300:]})
    if kind in ("keys_once", "marks", "information_kept") and evidence.get("page") is None:
        return out(None, {"why": "the page was not observed after the change"})
    page = evidence.get("page") or {}
    if kind == "keys_once":
        wrong = sorted(k for k in spec["keys"] if len(_rows_of(page, k)) != 1)
        return out(not wrong, {"keys": len(spec["keys"]), "not_once": wrong[:20]})
    if kind == "information_kept":
        if "lines" not in page:
            return out(None, {"why": "the page's text was not recorded"})
        lost = sorted(set(spec["lines"]) - info_lines(page["lines"], set(spec.get("keys", []))))
        return out(not lost, {"lost": lost[:10]})
    if kind == "marks":
        unmarked = sorted(k for k in spec["flag_keys"] if not any(_marked(r, spec) for r in _rows_of(page, k)))
        marked = sorted(k for k in spec["plain_keys"] if any(_marked(r, spec) for r in _rows_of(page, k)))
        observed = {"should_be_marked_and_are_not": unmarked[:20], "marked_and_should_not_be": marked[:20]}
        return out(not unmarked and not marked, observed)
    if kind == "action_effect":
        verification = evidence.get("verification")
        if not verification:
            return out(None, {"why": "the effect was not read back"})
        return out(bool(verification.get("verified")), {"how": verification.get("how", "")[:300]})
    return out(None, {"why": f"no evaluator for {kind}"})


def judge(acc: Acceptance, evidence: dict[str, Any], basis: str, model_claim: str) -> Acceptance:
    """Evaluate every fixed condition on what is deployed (`basis`), then decide. The model's claim is kept apart."""
    if Acceptance.seal(acc.conditions) != acc.sealed:
        raise ConditionsChanged(f"{acc.id}: its conditions changed after they were fixed; nothing is judged")
    acc.model_claim = model_claim  # type: ignore[assignment]
    acc.outcomes = [evaluate(c, evidence, basis) for c in acc.conditions]
    failed = [o.condition for o in acc.outcomes if o.status == "failed"]
    unverifiable = [o.condition for o in acc.outcomes if o.status == "unverifiable"]
    if failed:
        acc.state, acc.why = "rejected", f"not satisfied: {', '.join(failed)}"
    elif unverifiable:
        acc.state, acc.why = "inconclusive", f"could not be checked: {', '.join(unverifiable)}"
    elif model_claim != "resolved":
        acc.state, acc.why = "inconclusive", f"the checks pass and the model's own re-check says {model_claim}"
    else:
        acc.state, acc.why = "accepted", "every fixed condition satisfied on what is deployed"
    return acc


def refresh(store: Store, subject_prefix: str, basis_now: str) -> list[Acceptance]:
    """Accepted results observed on another deployed commit are stale: what was checked is not what runs now."""
    stale = []
    for acc in store.list(COLLECTION, Acceptance):
        moved = any(o.basis != basis_now for o in acc.outcomes)
        if acc.subject.startswith(subject_prefix) and acc.state == "accepted" and moved:
            acc.state, acc.why = "stale", f"observed on {acc.outcomes[0].basis[:12]}; {basis_now[:12]} is deployed"
            store.put(COLLECTION, acc)
            stale.append(acc)
    return stale
