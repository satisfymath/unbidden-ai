"""Build the World Model: repository, running system, deploy, then inferred relations; reconcile it with the
previous map, store it and say what changed."""

from __future__ import annotations

from pathlib import Path

from unbidden.brain.router import Brain
from unbidden.contracts.common import EpistemicStatus, EvidenceRef
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.guardian import ActionRequest, Mandate
from unbidden.contracts.world import BlindSpot, Deployment, Relation, Resource, RunningContainer, WorldModel
from unbidden.guardian.policy import PolicyEngine
from unbidden.guardian.scanner import SensitiveTermIndex
from unbidden.observe.stack import detect_stack
from unbidden.operate import ledger
from unbidden.store import Store
from unbidden.workspace import head_sha
from unbidden.world import prometheus
from unbidden.world.checks import run_checks
from unbidden.world.connectors import (
    COMPOSE_DOCKER,
    GIT_STATIC,
    LEDGER,
    LLM_RELATIONS,
    OPENAPI_HTTP,
    POSTGRES_READONLY,
    PROMETHEUS,
)
from unbidden.world.reconcile import reconcile
from unbidden.world.relations import infer_endpoint_tables
from unbidden.world.runtime import compose_files, discover_runtime
from unbidden.world.static import discover_static

COLLECTION = "world"
RUNTIME_SOURCES = {COMPOSE_DOCKER.ref, OPENAPI_HTTP.ref, POSTGRES_READONLY.ref}


def app_services(world: WorldModel) -> set[str]:
    """Services whose code is the repository's: those serving endpoints, else those built from it."""
    serving = {str(r.attributes.get("service")) for r in world.of_kind("endpoint") if r.attributes.get("service")}
    if serving:
        return serving
    return {r.name for r in world.of_kind("service") if r.attributes.get("build")}


def add_deployment(world: WorldModel, deployment: Deployment, containers: list[RunningContainer]) -> None:
    """The current deploy as a resource: the services it runs, the images its containers hold."""
    did = f"deployment:{deployment.id}"
    evidence = [EvidenceRef(kind="config", locator=f"deployments/{deployment.id}", note=deployment.commit_reason)]
    world.add(
        Resource(
            id=did,
            kind="deployment",
            name=f"deploy {deployment.id}",
            attributes={
                "commit": deployment.commit,
                "commit_status": deployment.commit_status,
                "commit_reason": deployment.commit_reason,
                "initiated_by": deployment.initiated_by,
                "environment": deployment.environment,
                "seen_at": deployment.seen_at.isoformat(),
            },
            status=EpistemicStatus.OBSERVED,
            confidence=1.0,
            evidence=evidence,
            source=LEDGER.ref,
            environment=deployment.environment,
            valid_for=did,
        )
    )
    for c in containers:
        image = f"image:{c.image_id.removeprefix('sha256:')[:12]}"
        locator = f"docker inspect {c.name}"
        world.add(
            Resource(
                id=image,
                kind="image",
                name=c.image_id,
                attributes={"created": c.image_created, "revision_label": c.revision_label, "service": c.service},
                status=EpistemicStatus.OBSERVED,
                confidence=1.0,
                evidence=[EvidenceRef(kind="config", locator=locator)],
                source=COMPOSE_DOCKER.ref,
                environment=deployment.environment,
                valid_for=did,
            )
        )
        if f"container:{c.name}" in world.resources:
            world.relate(
                Relation(
                    src=f"container:{c.name}",
                    dst=image,
                    predicate="runs_image",
                    status=EpistemicStatus.OBSERVED,
                    confidence=1.0,
                    evidence=[EvidenceRef(kind="config", locator=locator)],
                    source=COMPOSE_DOCKER.ref,
                    environment=deployment.environment,
                    valid_for=did,
                )
            )
        world.relate(
            Relation(
                src=did,
                dst=f"service:{c.service}",
                predicate="deploys",
                status=EpistemicStatus.OBSERVED,
                confidence=1.0,
                evidence=evidence,
                source=LEDGER.ref,
                environment=deployment.environment,
                valid_for=did,
            )
        )


def _text_needs(world: WorldModel, store: Store) -> None:
    """Text metrics endpoints nothing reads yet are a need, named with what would fill it."""
    from unbidden.forge import stats_build

    for container in world.of_kind("container"):
        for endpoint in container.attributes.get("text_endpoints", []):
            url, fmt = endpoint["url"], endpoint["format"]
            if stats_build.usable(store, url) is not None:
                endpoint["reader"] = "forge"
                continue
            why = (
                f"{endpoint['lines']} lines in {fmt}, a known format: read it through a reader that exists"
                if fmt != "unknown"
                else f"{endpoint['lines']} lines of numbers in a format no connector reads; "
                f"`unbidden forge stats {url}` can build a reader"
            )
            world.blind_spots.append(
                BlindSpot(what=f"metrics at {url} ({container.attributes.get('service')})", why=why)
            )


def _metrics(repo: Path, world: WorldModel) -> set[str]:
    """The project's own Prometheus, when it runs one. Unreachable is a blind spot; what it saw before is kept."""
    url = prometheus.find(world)
    if url is None:
        return set()
    try:
        prometheus.observe(prometheus.Prometheus(url), world, prometheus.project_ips(repo))
    except prometheus.PrometheusError as exc:
        world.blind_spots.append(BlindSpot(what="metrics", why=f"the project's Prometheus could not be read: {exc}"))
        return set()
    return {PROMETHEUS.ref}


async def discover(repo: Path, rev: str, store: Store, mandate: Mandate, brain: Brain | None) -> WorldModel:
    policy = PolicyEngine(mandate)
    previous = store.get(COLLECTION, "world", WorldModel)
    world = WorldModel(rev=rev)
    ran: set[str] = set()
    runtime_allowed = policy.evaluate(ActionRequest(capability="runtime.read", purpose="map the running system"))
    # The files the deployment was started with, when it runs: they declare what actually runs.
    files = compose_files(repo) if runtime_allowed.allowed else []
    if policy.evaluate(ActionRequest(capability="repo.read", purpose="map the repository")).allowed:
        discover_static(repo, rev, detect_stack(repo, rev), world, files or None)
        world.stamp(GIT_STATIC.ref, valid_for=rev)
        ran.add(GIT_STATIC.ref)
    else:
        world.blind_spots.append(BlindSpot(what="the repository", why="repo.read is not allowed by the mandate"))
    if runtime_allowed.allowed:
        ran |= discover_runtime(repo, world, rev, files or None)
        containers = [c for c in ledger.snapshot(repo) if c.service in app_services(world)]
        deployment = ledger.observe(store, containers, head_sha(repo)) if containers else None
        if deployment is not None:
            ran.add(LEDGER.ref)
            add_deployment(world, deployment, containers)
            for fact in [*world.resources.values(), *world.relations]:
                if fact.source in RUNTIME_SOURCES and fact.valid_for is None:
                    fact.valid_for = f"deployment:{deployment.id}"
                    fact.environment = deployment.environment
        ran |= _metrics(repo, world)
    else:
        world.blind_spots.append(BlindSpot(what="the running system", why="runtime.read is not allowed by the mandate"))
    _text_needs(world, store)
    if brain is not None:
        await infer_endpoint_tables(repo, rev, world, brain)
        world.stamp(LLM_RELATIONS.ref, valid_for=rev)
        ran.add(LLM_RELATIONS.ref)
    world, diff = reconcile(previous, world, ran)
    store.put(COLLECTION, world)
    run_checks(world, store)
    store.append_event(
        Event(
            type=EventType.WORKSPACE_INITIALIZED if previous is None else EventType.WORLD_CHANGED,
            actor="world",
            entity_id=world.id,
            payload={
                "rev": rev,
                "resources": len(world.resources),
                "relations": len(world.relations),
                "blind_spots": len(world.blind_spots),
                "sources_ran": sorted(ran),
                "diff": diff.summary(),
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
