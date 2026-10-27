"""The deploy ledger: which code each set of running containers holds, and how that is known.

A deploy used to be "new container IDs appeared", with the checkout's HEAD at that moment taken as the code they
run. That is a guess: a person may have built from another checkout, or restarted old images. Now the commit
of a deploy is resolved from evidence, and says which:

1. `observed`: the images carry `org.opencontainers.image.revision`.
2. `verified`: Unbidden ran the deploy steps for that commit, and those steps build images from the checkout
   (an image reused from the build cache is still that commit's build: same inputs, same image ID), or the
   image was created inside that deploy. Bound at deploy time, image ID -> commit.
3. `inferred`: the checkout's HEAD when the containers were first seen, with that reason written down.
4. `unknown`: none of the above.

Only containers of this workspace's compose project are read: `docker compose --project-directory` scopes the
listing, and each inspected container must also carry this project's label.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from unbidden.contracts.common import utc_now
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.world import CommitStatus, Deployment, RunningContainer
from unbidden.store import Store
from unbidden.world.runtime import running_containers

REVISION_LABEL = "org.opencontainers.image.revision"
PROJECT_LABEL = "com.docker.compose.project"
ENVIRONMENT = "local-compose"
UNBIDDEN_DEPLOY_WINDOW = timedelta(minutes=30)
COLLECTION = "deployments"
STRENGTH = {"unknown": 0, "inferred": 1, "observed": 2, "verified": 2}


def parse_ts(value: str | None) -> datetime | None:
    """Docker timestamps carry nanoseconds and any offset: `2026-10-27T01:29:07.723889263Z`."""
    if not value or value.startswith("0001-"):
        return None
    text = value.strip().replace("Z", "+00:00")
    head, dot, rest = text.partition(".")
    if dot:
        digits = rest[: len(rest) - len(rest.lstrip("0123456789"))]
        offset = rest[len(digits) :]
        text = f"{head}.{digits[:6]}{offset}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _docker_json(*args: str) -> list[dict[str, Any]]:
    out = subprocess.run(["docker", *args], capture_output=True, text=True, check=False)
    if out.returncode != 0 or not out.stdout.strip():
        return []
    data = json.loads(out.stdout)
    return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []  # pyright: ignore[reportUnknownVariableType]


def containers_from(
    rows: list[dict[str, Any]], inspected: list[dict[str, Any]], images: list[dict[str, Any]]
) -> list[RunningContainer]:
    """Pure: the project's containers from `compose ps` rows and `docker inspect` output. A container whose
    project label is not the listing's project is dropped, whatever the listing said."""
    projects = {str(r.get("Project")) for r in rows if r.get("Project")}
    created = {str(i.get("Id")): str(i.get("Created") or "") for i in images}
    digests = {str(i.get("Id")): (i.get("RepoDigests") or [None])[0] for i in images}
    found: list[RunningContainer] = []
    for item in inspected:
        labels: dict[str, str] = (item.get("Config") or {}).get("Labels") or {}
        if projects and labels.get(PROJECT_LABEL) not in projects:
            continue
        image_id = str(item.get("Image", ""))
        found.append(
            RunningContainer(
                service=labels.get("com.docker.compose.service", ""),
                container_id=str(item.get("Id", "")),
                name=str(item.get("Name", "")).lstrip("/"),
                image_id=image_id,
                image_created=created.get(image_id) or None,
                started_at=(item.get("State") or {}).get("StartedAt"),
                revision_label=labels.get(REVISION_LABEL) or None,
                repo_digest=digests.get(image_id),
            )
        )
    return sorted(found, key=lambda c: c.service)


def snapshot(repo: Path) -> list[RunningContainer]:
    rows = running_containers(repo)
    ids = [str(r["ID"]) for r in rows if r.get("ID")]
    if not ids:
        return []
    inspected = _docker_json("inspect", *ids)
    image_ids = sorted({str(i.get("Image")) for i in inspected if i.get("Image")})
    images = _docker_json("image", "inspect", *image_ids) if image_ids else []
    return containers_from(rows, inspected, images)


def from_registry(container: RunningContainer) -> bool:
    """Whether the image came from a registry. A digest alone does not say so: Docker's containerd image store
    gives local builds one too (`backend@sha256:...`). Only a digest naming a registry host does."""
    if not container.repo_digest:
        return False
    repository = container.repo_digest.split("@", 1)[0]
    host = repository.split("/", 1)[0]
    return "/" in repository and ("." in host or ":" in host or host == "localhost")


def steps_build(steps: list[list[str]]) -> bool:
    """Whether declared deploy steps build images from the checkout (`docker compose up --build`, `docker build`)."""
    return any("--build" in argv or (len(argv) > 2 and argv[0] == "docker" and "build" in argv[1:3]) for argv in steps)


def bind(
    store: Store, containers: list[RunningContainer], commit: str, started: datetime, *, rebuilt: bool = False
) -> dict[str, Any]:
    """After Unbidden's own deploy of `commit`: remember which images hold it. A binding is verified when the deploy
    steps built from the checkout or the image was created inside this deploy; a container merely restarted on an
    older image proves nothing."""
    bindings: dict[str, dict[str, Any]] = store.get_value("image_bindings", {})
    record: dict[str, Any] = {}
    for c in containers:
        built = parse_ts(c.image_created)
        # Build steps vouch only for images built here; one pulled from a registry was not built from the checkout.
        verified = (rebuilt and not from_registry(c)) or (built is not None and built >= started)
        if c.image_id in bindings and bindings[c.image_id].get("verified") and not verified:
            continue  # an earlier deploy built this image; that binding stays
        bindings[c.image_id] = {
            "commit": commit,
            "verified": verified,
            "service": c.service,
            "at": utc_now().isoformat(),
            "reason": (
                "built from this commit's checkout by the deploy steps (a cached build is the same build)"
                if rebuilt
                else "image created during Unbidden's deploy of this commit"
            )
            if verified
            else "the deploy steps did not rebuild this image; the code it holds predates the deploy",
        }
        record[c.service] = bindings[c.image_id]
    store.set_value("image_bindings", bindings)
    # Every deploy Unbidden ran (a drill's two included), so the containers it starts are credited to it.
    ran: list[dict[str, str]] = store.get_value("unbidden_deploys", [])
    store.set_value("unbidden_deploys", [*ran[-49:], {"commit": commit, "at": utc_now().isoformat()}])
    return record


def bind_after_deploy(
    repo: Path, store: Store, commit: str, started: datetime, *, rebuilt: bool = False
) -> dict[str, Any]:
    return bind(store, snapshot(repo), commit, started, rebuilt=rebuilt)


def resolve(
    containers: list[RunningContainer], bindings: dict[str, dict[str, Any]], head: str | None
) -> tuple[str | None, CommitStatus, str]:
    """The commit a set of application containers runs, with how it is known."""
    if not containers:
        return None, "unknown", "no application container"
    labels = {c.revision_label for c in containers}
    if None not in labels and len(labels) == 1:
        return labels.pop(), "observed", f"image label {REVISION_LABEL}"
    bound = [bindings.get(c.image_id) for c in containers]
    commits = {b["commit"] for b in bound if b}
    if all(bound) and len(commits) == 1:
        commit = commits.pop()
        if all(b and b.get("verified") for b in bound):
            return commit, "verified", "images built by Unbidden's deploy of this commit"
        return commit, "inferred", "deployed by Unbidden, but images were not rebuilt by that deploy"
    if len(commits) > 1:
        return None, "unknown", "containers hold images bound to different commits: " + ", ".join(sorted(commits))
    pulled = [c for c in containers if from_registry(c)]
    if pulled and len(pulled) == len(containers):
        return (
            None,
            "unknown",
            f"images pulled from a registry ({pulled[0].repo_digest}), not built from this checkout; "
            "they carry no revision label",
        )
    if head:
        return (
            head,
            "inferred",
            "the checkout's HEAD when these containers were first seen; nothing in the images says what code they hold",
        )
    return None, "unknown", "no label, no binding, no checkout"


def initiator(store: Store, containers: list[RunningContainer], commit: str | None) -> str:
    """Who started these containers. `unbidden` when its last deploy of this commit finished within minutes of the
    containers starting; `external` when the ledger was already watching before they started and Unbidden did not
    deploy them; `unknown` when they started before anything was watching."""
    starts = [t for c in containers if (t := parse_ts(c.started_at)) is not None]
    if not starts:
        return "unknown"
    started = max(starts)
    last: dict[str, Any] | None = store.get_value("deployed_by_unbidden")
    ours: list[dict[str, Any]] = [*store.get_value("unbidden_deploys", []), *([last] if last else [])]
    for record in ours:
        at = parse_ts(record.get("at"))
        if commit and record.get("commit") == commit and at is not None and abs(at - started) <= UNBIDDEN_DEPLOY_WINDOW:
            return "unbidden"
    watching = [d.seen_at for d in store.list(COLLECTION, Deployment)]
    return "external" if watching and min(watching) < started else "unknown"


def version_of(deployment: Deployment) -> str:
    """The version string probe rounds are tagged with: the commit, or an image-derived id when it is unknown."""
    if deployment.commit:
        return deployment.commit
    images = ",".join(sorted(c.image_id.removeprefix("sha256:")[:12] for c in deployment.containers))
    return f"unknown-{images}"


def observe(
    store: Store, containers: list[RunningContainer], head: str | None, *, now: datetime | None = None
) -> Deployment | None:
    """Record a deploy when this set of application containers is new; return the deploy they belong to.

    Containers recreated on the same code are the same deploy (as before); the same code deployed again after
    another version is a new deploy (a rollback).
    """
    if not containers:
        return None
    now = now or utc_now()
    key = ",".join(sorted(c.container_id for c in containers))
    known: dict[str, str] = store.get_value("container_deploys", {})
    if key in known:
        return store.get(COLLECTION, known[key], Deployment)
    latest = deployments(store)[-1:]
    if latest and {c.container_id for c in containers} <= {c.container_id for c in latest[0].containers}:
        return latest[0]  # containers stopped or restarted, none new: not a deploy
    commit, status, reason = resolve(containers, store.get_value("image_bindings", {}), head)
    initiated = initiator(store, containers, commit)
    sequence: list[str] = store.get_value("deploy_sequence", [])
    draft = Deployment(
        id="pending",
        index=-1,
        environment=ENVIRONMENT,
        containers=containers,
        commit=commit,
        commit_status=status,
        commit_reason=reason,
        initiated_by=initiated,  # type: ignore[arg-type]
        seen_at=now,
    )
    version = version_of(draft)
    if sequence and sequence[-1] == version:
        index = len(sequence) - 1
        current = store.get(COLLECTION, str(index), Deployment)
        if current is not None:
            current.containers = containers
            # Recreated on the same code: keep the deploy, but better evidence about it replaces weaker.
            if STRENGTH[status] > STRENGTH[current.commit_status]:
                current.commit_status, current.commit_reason = status, reason
            if initiated == "unbidden":
                current.initiated_by = "unbidden"
            store.put(COLLECTION, current)
            known[key] = current.id
            store.set_value("container_deploys", known)
            return current
    else:
        sequence = [*sequence, version]
        store.set_value("deploy_sequence", sequence)
        index = len(sequence) - 1
    deployment = draft.model_copy(update={"id": str(index), "index": index})
    store.put(COLLECTION, deployment)
    known[key] = deployment.id
    store.set_value("container_deploys", known)
    store.append_event(
        Event(
            type=EventType.DEPLOYMENT_OBSERVED,
            actor="observer",
            entity_id=deployment.id,
            payload={
                "commit": commit,
                "commit_status": status,
                "reason": reason,
                "initiated_by": initiated,
                "images": {c.service: c.image_id for c in containers},
            },
        )
    )
    return deployment


def deployments(store: Store) -> list[Deployment]:
    return sorted(store.list(COLLECTION, Deployment), key=lambda d: d.index)


def ran_commit(store: Store, commit: str, contains: Any = None) -> list[tuple[Deployment, str]]:
    """Deploys that ran `commit` exactly, or (when `contains(version, commit)` is given) a descendant of it."""
    found: list[tuple[Deployment, str]] = []
    for d in deployments(store):
        if d.commit and d.commit.startswith(commit):
            found.append((d, "runs exactly this commit"))
        elif d.commit and contains is not None and contains(d.commit, commit):
            found.append((d, "runs a descendant that contains this commit"))
    return found


def is_attributable(deployment: Deployment | None) -> bool:
    """A deploy's measurements can be credited to code only when its commit is verified or observed."""
    return deployment is not None and deployment.commit_status in ("verified", "observed")
