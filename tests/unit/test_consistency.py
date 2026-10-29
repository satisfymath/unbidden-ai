"""Unbidden's own question about an API's reported numbers (stage 9): raised by the live document's structure,
investigated once, read-only, and decided by what was found."""

from __future__ import annotations

import pytest

from unbidden.contracts.common import EpistemicStatus, EvidenceRef
from unbidden.contracts.guardian import Mandate
from unbidden.contracts.opportunity import ActionKind
from unbidden.contracts.world import Resource, WorldModel
from unbidden.director.decide import Context, decide
from unbidden.world.checks import reported_aggregates
from unbidden.world.runtime import reported_aggregates as fields_of

pytestmark = pytest.mark.unit
SPEC = {
    "components": {"schemas": {
        "Item": {"type": "object", "properties": {"id": {"type": "integer"}, "likesCount": {"type": "integer"},
                                                  "title": {"type": "string"}}},
        "List": {"type": "object", "properties": {
            "items": {"type": "array", "items": {"$ref": "#/components/schemas/Item"}}, "total": {"type": "integer"}}},
    }},
}  # fmt: skip
OPERATION = {"responses": {"200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/List"}}}}}}


SEEN = [EvidenceRef(kind="config", locator="openapi")]


def world_with(endpoints: list[tuple[str, list[str]]]) -> WorldModel:
    world = WorldModel(rev="r")
    world.add(
        Resource(
            id="table:items", kind="table", name="items", status=EpistemicStatus.OBSERVED, confidence=1, evidence=SEEN
        )
    )
    for name, aggregates in endpoints:
        attributes = {"aggregates": aggregates, "service": "app"}
        world.add(Resource(id=f"endpoint:{name}", kind="endpoint", name=name, status=EpistemicStatus.OBSERVED,
                           confidence=1, evidence=SEEN, attributes=attributes))  # fmt: skip
    return world


def test_reported_numbers_raise_a_question_on_listings_only() -> None:
    assert fields_of(SPEC, OPERATION) == ["items[].likesCount", "total"]  # ids and strings are not numbers of things
    found = reported_aggregates(world_with([("GET /items", fields_of(SPEC, OPERATION)), ("GET /items/{id}", ["n"]),
                                            ("POST /items", ["total"]), ("GET /tags", [])]))  # fmt: skip
    assert [o.details["endpoint"] for o in found] == ["GET /items"] and found[0].category == "bugs"


@pytest.mark.parametrize(
    ("result", "chosen"),
    [
        (None, ActionKind.INVESTIGATE),
        ({"status": "investigated", "discrepancies": [{"id": 1}], "note": "1 of 9 keys differ"}, ActionKind.WAIT),
        ({"status": "investigated", "discrepancies": [], "note": "0 of 9 keys differ"}, ActionKind.DECLINE),
        ({"status": "inconclusive", "note": "completeness unknown"}, ActionKind.WAIT),
        ({"status": "blocked", "note": "no integration"}, ActionKind.WAIT),
    ],
)
def test_the_question_is_investigated_once_and_decided_by_what_was_found(
    result: dict[str, object] | None, chosen: ActionKind
) -> None:
    (opp,) = reported_aggregates(world_with([("GET /items", ["total"])]))
    if result is not None:
        opp.details = {**opp.details, "consistency": result, "investigations": 1}
    mandate = Mandate(workspace="w", priorities=["correctness"])
    assert decide(opp, mandate, Context(open_pull_requests=0, attempts=0)).chosen is chosen
    opp.details = {**opp.details, "investigations": 1}
    if result is None:  # once queued, never queued again while it runs
        assert decide(opp, mandate, Context(open_pull_requests=0, attempts=0)).chosen is ActionKind.WAIT
