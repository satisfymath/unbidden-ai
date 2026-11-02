"""The feed narrates every event type, folds runs of alike events, and seeds from the highlights."""

from __future__ import annotations

import pytest

from unbidden.contracts.events import Event, EventType
from unbidden.store.sqlite import Store
from unbidden.tui import feed
from unbidden.tui.feed import Coalescer, narrate, seed

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("event_type", list(EventType))
def test_every_event_type_has_a_verb_and_a_line_even_with_an_empty_payload(event_type: EventType) -> None:
    assert event_type in feed.VERB_OF
    entry = narrate(Event(type=event_type, actor="t"), verbose=True)
    assert entry is not None
    assert entry.verb == feed.VERB_OF[event_type]
    assert entry.text and "{" not in entry.text  # every placeholder filled


def test_allowed_egress_is_quiet_unless_verbose() -> None:
    e = Event(type=EventType.EGRESS_ALLOWED, actor="t", payload={"bytes": 12, "destination": "api.meta.ai"})
    assert narrate(e) is None
    assert narrate(e, verbose=True) is not None


def test_a_decision_a_verdict_and_a_proposal_read_as_the_brand_writes_them() -> None:
    decision = narrate(Event(type=EventType.DECISION_MADE, actor="director", correlation_id="opp_1", payload={
        "chosen": "experiment", "reason": "cheap and likely", "candidates": [{"kind": "experiment", "utility": 0.8}]
    }))  # fmt: skip
    assert decision is not None and decision.verb == "Deciding"
    assert decision.text == "experiment because cheap and likely" and decision.ref == "opp_1"
    assert decision.detail == "candidates: experiment 0.8"
    verdict = narrate(Event(type=EventType.VERDICT_RECORDED, actor="lab", correlation_id="opp_1", payload={
        "improved": True, "level": 4, "median_before_ms": 13.0, "median_after_ms": 4.1, "p_value": 3.4e-08,
    }))  # fmt: skip
    assert verdict is not None and verdict.verb == "Proving"
    assert verdict.text == "Improved, L4: 13.0 → 4.1 ms, p = 3.4e-08."
    ready = Event(type=EventType.PROPOSAL_READY, actor="lab", correlation_id="opp_1",
                  payload={"branch": "unbidden/opp_1", "commit": "abcdef1234567890", "level": 4})  # fmt: skip
    assert narrate(ready) is not None and narrate(ready).verb == "Proving"  # type: ignore[union-attr]
    asked = narrate(ready, asks_for_proposals=True)
    assert asked is not None and asked.verb == "Asking" and asked.accent
    assert "/approve opp_1" in asked.text


def test_long_texts_are_clipped() -> None:
    entry = narrate(Event(type=EventType.OPPORTUNITY_OPENED, actor="t", payload={"title": "x" * 500}))
    assert entry is not None and len(entry.text) == feed.TEXT_LIMIT and entry.text.endswith("…")


def test_runs_of_model_calls_fold_into_one_line_and_other_events_break_the_run() -> None:
    folder = Coalescer()
    payload = {"purpose": "probe", "tier": "code", "model": "m", "tokens_in": 100, "tokens_out": 50, "usd": 0.01,
               "ok": True}  # fmt: skip
    calls = [
        Event(type=EventType.MODEL_CALLED, actor="brain", correlation_id="opp_1", payload=payload) for _ in range(3)
    ]
    out: list[feed.Entry] = []
    for c in calls:
        out.extend(folder.push(c))
    assert out == []
    out.extend(folder.push(Event(type=EventType.OPPORTUNITY_OPENED, actor="t", payload={"title": "found"})))
    assert [e.text for e in out] == ["3 model calls · 450 tokens · US$0.0300", "Found: found"]
    assert folder.flush() == []


def test_of_a_run_of_head_moves_only_the_last_is_kept() -> None:
    folder = Coalescer()
    for i in range(3):
        folder.push(Event(type=EventType.HEAD_MOVED, actor="observer", payload={"from": f"a{i}", "to": f"b{i}"}))
    out = folder.flush()
    assert [e.text for e in out] == ["Head moved a2 → b2."]


def test_seed_shows_where_things_stand_then_the_last_events(store: Store) -> None:
    for i in range(5):
        store.append_event(Event(type=EventType.OPPORTUNITY_OPENED, actor="t", payload={"title": f"finding {i}"}))
    highlights = [{"id": "opp_1", "title": "an index", "level": 4, "status": "proposed", "has_experiment": True}]
    entries = seed(store, highlights, last=3, asks_for_proposals=True)
    assert entries[0].kind == "heading" and entries[0].text == "Where things stand."
    assert entries[1].verb == "Asking" and "/approve opp_1" in entries[1].text and entries[1].accent
    assert entries[2].kind == "heading" and entries[2].text == "The last 3 things it did."
    assert [e.text for e in entries[3:]] == ["Found: finding 2", "Found: finding 3", "Found: finding 4"]


def test_seed_without_anything_says_so(store: Store) -> None:
    entries = seed(store, [])
    assert [e.text for e in entries][1].startswith("Nothing found yet.")
