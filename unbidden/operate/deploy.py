"""Deploys and rollbacks run the team's own declared steps, against a commit chosen by evidence.

Unbidden never invents how to deploy: `mandate.operations.deploy_steps` are argv lists a person declared.
A deploy moves the deployment checkout to a commit (fast-forward to the merged base, or a detached rollback
to the last healthy commit), then runs those steps in it.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import httpx

from unbidden.contracts.common import utc_now
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.guardian import ActionRequest, Mandate
from unbidden.guardian.policy import PolicyEngine
from unbidden.operate.holds import active
from unbidden.store import Store


class OperationRefused(RuntimeError):
    pass


@dataclass(frozen=True)
class DeployResult:
    ok: bool
    commit: str
    log: str


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)


def _recent(store: Store, key: str, window: timedelta) -> list[str]:
    stamps: list[str] = store.get_value(key, [])
    since = (utc_now() - window).isoformat()
    return [s for s in stamps if s >= since]


def check(store: Store, mandate: Mandate, capability: str, purpose: str, *, rate_key: str, limit: int) -> None:
    """Guardian, holds and rate limits, in that order. Raises when the operation may not run."""
    verdict = PolicyEngine(mandate).evaluate(ActionRequest(capability=capability, purpose=purpose))
    if not verdict.allowed:
        raise OperationRefused(f"{capability}: {'; '.join(verdict.reasons)}")
    holds = active(store)
    if holds and capability != "deploy.rollback":
        raise OperationRefused(f"held: {holds[0].reason} (release with `unbidden hold release {holds[0].id}`)")
    if len(_recent(store, rate_key, timedelta(hours=1))) >= limit:
        raise OperationRefused(f"{capability}: {limit} already in the last hour")


def run_steps(repo: Path, mandate: Mandate, commit: str, *, detach: bool) -> DeployResult:
    steps = mandate.operations.deploy_steps
    if not steps:
        raise OperationRefused("the mandate declares no deploy steps")
    log: list[str] = []
    move = _git(repo, "checkout", "--detach", commit) if detach else _git(repo, "merge", "--ff-only", commit)
    log.append(
        f"$ git {'checkout --detach' if detach else 'merge --ff-only'} {commit[:12]}\n{move.stdout}{move.stderr}"
    )
    if move.returncode != 0:
        return DeployResult(False, commit, "\n".join(log))
    for argv in steps:
        out = subprocess.run(argv, cwd=repo, capture_output=True, text=True, check=False, timeout=1800)
        log.append(f"$ {' '.join(argv)}\n{out.stdout[-2000:]}{out.stderr[-2000:]}")
        if out.returncode != 0:
            return DeployResult(False, commit, "\n".join(log))
    return DeployResult(True, commit, "\n".join(log))


def deploy(
    repo: Path, store: Store, mandate: Mandate, commit: str, *, reason: str, rollback: bool = False
) -> DeployResult:
    capability = "deploy.rollback" if rollback else "deploy.run"
    key = "rollbacks" if rollback else "deploys"
    check(store, mandate, capability, reason, rate_key=key, limit=mandate.operations.max_deploys_per_hour + rollback)
    result = run_steps(repo, mandate, commit, detach=rollback)
    store.set_value(key, [*_recent(store, key, timedelta(hours=24)), utc_now().isoformat()])
    store.append_event(
        Event(
            type=EventType.DEPLOYED,
            actor="operator",
            entity_id=commit,
            payload={
                "commit": commit,
                "rollback": rollback,
                "ok": result.ok,
                "reason": reason,
                "log_tail": result.log[-1500:],
            },
        )
    )
    if result.ok:
        store.set_value("deployed_by_unbidden", {"commit": commit, "at": utc_now().isoformat(), "rollback": rollback})
    return result


def healthy(url: str, *, attempts: int = 30, every_s: float = 2.0) -> bool:
    for _ in range(attempts):
        try:
            if httpx.get(url, timeout=5).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(every_s)
    return False


def drill(repo: Path, store: Store, mandate: Mandate, previous: str, health_url: str) -> dict[str, object]:
    """Prove rollback works before autonomy may rely on it: go back one version, check health, come back."""
    current = _git(repo, "rev-parse", "HEAD").stdout.strip()
    branch = _git(repo, "branch", "--show-current").stdout.strip()
    back = run_steps(repo, mandate, previous, detach=True)
    back_ok = back.ok and healthy(health_url)
    _git(repo, "checkout", branch or current)
    forth = run_steps(repo, mandate, current, detach=not branch)
    forth_ok = forth.ok and healthy(health_url)
    record = {
        "at": utc_now().isoformat(),
        "from": current,
        "to": previous,
        "back": back_ok,
        "forth": forth_ok,
        "passed": back_ok and forth_ok,
    }
    store.set_value("rollback_drill", record)
    store.append_event(Event(type=EventType.DEPLOYED, actor="operator", payload={"drill": record}))
    return record
