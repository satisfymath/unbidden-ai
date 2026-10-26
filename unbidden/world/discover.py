"""Build the World Model: repository, running system, then inferred relations; store it and say what changed."""

from __future__ import annotations

from pathlib import Path

from unbidden.brain.router import Brain
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.guardian import ActionRequest, Mandate
from unbidden.contracts.world import WorldModel
from unbidden.guardian.policy import PolicyEngine
from unbidden.guardian.scanner import SensitiveTermIndex
from unbidden.observe.stack import detect_stack
from unbidden.store import Store
from unbidden.world.relations import infer_endpoint_tables
from unbidden.world.runtime import discover_runtime
from unbidden.world.static import discover_static

COLLECTION = "world"


async def discover(repo: Path, rev: str, store: Store, mandate: Mandate, brain: Brain | None) -> WorldModel:
    policy = PolicyEngine(mandate)
    world = WorldModel(rev=rev)
    if policy.evaluate(ActionRequest(capability="repo.read", purpose="map the repository")).allowed:
        discover_static(repo, rev, detect_stack(repo, rev), world)
    if policy.evaluate(ActionRequest(capability="runtime.read", purpose="map the running system")).allowed:
        discover_runtime(repo, world)
    if brain is not None:
        await infer_endpoint_tables(repo, rev, world, brain)
    store.put(COLLECTION, world)
    store.append_event(
        Event(
            type=EventType.WORKSPACE_INITIALIZED,
            actor="world",
            entity_id=world.id,
            payload={
                "rev": rev,
                "resources": len(world.resources),
                "relations": len(world.relations),
                "blind_spots": len(world.blind_spots),
            },
        )
    )
    return world


def sensitive_terms(world: WorldModel) -> SensitiveTermIndex:
    """Real names of this environment that must never reach a remote model."""
    terms: list[str] = []
    for resource in world.resources.values():
        if resource.kind in ("table", "service", "database", "container", "repo"):
            terms.append(resource.name)
        if resource.kind == "endpoint":
            terms.extend(seg for seg in resource.name.split(" ", 1)[-1].split("/") if seg and "{" not in seg)
    return SensitiveTermIndex(terms)
