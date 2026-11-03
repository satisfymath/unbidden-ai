"""Campaign 12, phase 6 (spoolman): the endpoint-to-table reading asks the local model once per batch of handlers,
and never again for a handler whose code has not changed."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from unbidden.contracts.common import EpistemicStatus, EvidenceRef
from unbidden.contracts.world import Resource, WorldModel
from unbidden.store import Store
from unbidden.world import relations
from unbidden.world.relations import BATCH_HANDLERS, _batches, infer_endpoint_tables  # pyright: ignore[reportPrivateUsage]

pytestmark = pytest.mark.unit
REF = [EvidenceRef(kind="file", locator="x")]


def _world(endpoints: int) -> WorldModel:
    world = WorldModel(rev="r")
    for name in ("items", "users"):
        world.add(Resource(id=f"table:{name}", kind="table", name=name, status=EpistemicStatus.OBSERVED,
                           confidence=1.0, evidence=REF))  # fmt: skip
    for i in range(endpoints):
        world.add(Resource(id=f"endpoint:GET /e{i}", kind="endpoint", name=f"GET /e{i}",
                           attributes={"file": f"api/e{i}.py", "line": 1}, status=EpistemicStatus.OBSERVED,
                           confidence=1.0, evidence=REF))  # fmt: skip
    return world


class FakeBrain:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    async def complete_json(self, request: Any) -> tuple[dict[str, Any], None]:
        self.requests.append(request)
        names = list(request.response_schema["properties"])
        return {n: {"reads": ["items"], "writes": ["users"] if n.endswith("0") else []} for n in names}, None


async def test_handlers_are_read_in_batches_and_unchanged_ones_are_not_asked_again(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    code = {f"api/e{i}.py": f"def e{i}(db):\n    return db.query(Item).all()\n" for i in range(10)}
    monkeypatch.setattr(relations, "handler_source", lambda repo, rev, file, line: code[file])
    brain = FakeBrain()
    world = _world(10)
    count = await infer_endpoint_tables(Path("."), "r", world, brain, store=store)  # type: ignore[arg-type]
    assert len(brain.requests) == 2 and [len(r.response_schema["required"]) for r in brain.requests] == [8, 2]
    assert count == 11 and len([r for r in world.relations if r.predicate == "reads"]) == 10
    assert (
        "GET /e0" in brain.requests[0].messages[0].content and "db.query(Item)" in brain.requests[0].messages[0].content
    )
    assert all(r.evidence[0].note and "handler" in r.evidence[0].note for r in world.relations)

    # The next map: the same handlers, nothing is asked; the relations are there again.
    again = _world(10)
    count = await infer_endpoint_tables(Path("."), "r", again, brain, store=store)  # type: ignore[arg-type]
    assert len(brain.requests) == 2 and count == 11 and len(again.relations) == 11

    # One handler changed: only it is asked.
    code["api/e3.py"] = "def e3(db):\n    return db.query(User).all()\n"
    changed = _world(10)
    await infer_endpoint_tables(Path("."), "r", changed, brain, store=store)  # type: ignore[arg-type]
    assert len(brain.requests) == 3 and brain.requests[-1].response_schema["required"] == ["GET /e3"]
    assert len(changed.relations) == 11


def test_a_batch_is_bounded_by_count_and_by_size() -> None:
    small = [(None, "f", 1, "x" * 100, "d")] * (BATCH_HANDLERS + 1)
    assert [len(b) for b in _batches(small)] == [BATCH_HANDLERS, 1]
    large = [(None, "f", 1, "x" * 7000, "d")] * 3
    assert [len(b) for b in _batches(large)] == [1, 1, 1]  # none over the size cap; the first always goes


async def test_a_refused_call_relates_nothing_and_caches_nothing(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    from unbidden.brain.router import SpendLimitReached

    monkeypatch.setattr(relations, "handler_source", lambda repo, rev, file, line: "def e(): ...")

    class Capped:
        async def complete_json(self, request: Any) -> Any:
            raise SpendLimitReached("at the cap")

    world = _world(2)
    assert await infer_endpoint_tables(Path("."), "r", world, Capped(), store=store) == 0  # type: ignore[arg-type]
    assert world.relations == [] and store.get_value("endpoint_tables:endpoint:GET /e0") is None
