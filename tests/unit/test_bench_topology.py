from __future__ import annotations

from typing import Any

import pytest

from bench.topology import score

pytestmark = pytest.mark.unit


def res(kind: str, name: str, status: str = "observed", **attrs: Any) -> dict[str, Any]:
    return {"kind": kind, "name": name, "status": status, "attributes": attrs}


def rel(src: str, predicate: str, dst: str, status: str = "inferred") -> dict[str, Any]:
    return {"src": src, "dst": dst, "predicate": predicate, "status": status}


def test_scores_claims_by_the_references_own_rules() -> None:
    reference = {
        "system": "s",
        "services": ["front", "cart", "collector"],
        "datastores": ["cache"],
        "relations": [["front", "cart"], ["cart", "cache"], ["front", "collector"]],
        "telemetry_plane": ["collector"],
    }
    world = {
        "resources": {
            "service:front": res("service", "front"),
            "service:cart": res("service", "cart"),
            "service:collector": res("service", "collector"),
            "service:cache": res("service", "cache", engine="redis"),
            "service:old": res("service", "old", status="obsolete"),
        },
        "relations": [
            rel("service:front", "calls", "service:cart"),
            rel("service:cart", "calls", "service:collector"),  # telemetry: listed, not scored
            rel("service:front", "depends_on", "service:cache", "observed"),  # start order, not a call
            rel("service:old", "calls", "service:cart", "obsolete"),
        ],
        "blind_spots": [],
    }
    result = score(reference, world)
    assert result["services"]["recall"] == 1.0 and result["services"]["precision"] == 1.0
    assert result["datastores"]["found"] == 1
    assert (result["relations"]["precision"], result["relations"]["recall"]) == (1.0, 0.5)
    assert result["relations"]["missed"] == ["('cart', 'cache')"]
    assert result["telemetry_edges_not_scored"] == ["cart -> collector"]
    assert result["depends_on_not_scored"] == ["front -> cache"]
