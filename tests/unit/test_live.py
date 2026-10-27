from __future__ import annotations

import random
import subprocess
from pathlib import Path
from typing import Any

import pytest

from unbidden.contracts.common import EpistemicStatus, EvidenceLevel, EvidenceRef
from unbidden.contracts.experiment import Proposal, ProposalStatus
from unbidden.contracts.guardian import Autonomy, Mandate
from unbidden.contracts.opportunity import Opportunity, OpportunityStatus
from unbidden.contracts.world import Deployment, Relation, Resource, WorldModel
from unbidden.observe import live as live_module
from unbidden.observe.live import DeployVerdict, LiveWatcher
from unbidden.operate.deploy import DeployResult
from unbidden.operate.holds import active
from unbidden.store import Store

pytestmark = pytest.mark.unit
A, B, C = "a" * 40, "b" * 40, "c" * 40
OBS = EpistemicStatus.OBSERVED


def add_rounds(
    store: Store, deploy: int, version: str, center: float, n: int, seed: int, target: str = "GET /items/"
) -> None:
    rng = random.Random(seed)
    for _ in range(n):
        store.add_round(target, version, [200] * 5, [center * rng.uniform(0.9, 1.1) for _ in range(5)], deploy=deploy)


def watcher(store: Store, mandate: Mandate, repo: Path = Path(".")) -> LiveWatcher:
    return LiveWatcher(repo, store, mandate, WorldModel(rev=A), log=lambda _: None)


def verdict(store: Store, key: str) -> DeployVerdict | None:
    return store.get("deploy_verdicts", key, DeployVerdict)


def test_waits_until_the_new_window_is_full(store: Store, mandate: Mandate) -> None:
    add_rounds(store, 0, A, 20, 20, 1)
    add_rounds(store, 1, B, 60, 5, 2)
    watcher(store, mandate)._judge([A, B], 1, 0)  # pyright: ignore[reportPrivateUsage]
    assert verdict(store, f"1:{B}") is None


def test_degraded_deploy_holds_and_rolls_back_to_the_last_healthy(
    store: Store, mandate: Mandate, monkeypatch: pytest.MonkeyPatch
) -> None:
    mandate.autonomy.rollback = Autonomy.ALLOW
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        live_module, "deploy", lambda *a, **k: calls.append({"commit": a[3], **k}) or DeployResult(True, a[3], "")
    )
    store.put("deploy_verdicts", DeployVerdict(id=f"1:{B}", previous=A, impact="healthy", endpoints=[], criteria={}))  # type: ignore[arg-type]
    add_rounds(store, 1, B, 20, 20, 1)
    add_rounds(store, 2, C, 60, 20, 2)
    watcher(store, mandate)._judge([A, B, C], 2, 1)  # pyright: ignore[reportPrivateUsage]
    judged = verdict(store, f"2:{C}")
    assert judged is not None and judged.impact.value == "degraded"
    assert len(calls) == 1 and calls[0]["commit"] == B and calls[0]["rollback"] is True
    assert len(active(store)) == 1


def test_without_rollback_autonomy_only_a_hold_is_placed(
    store: Store, mandate: Mandate, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[str] = []
    monkeypatch.setattr(live_module, "deploy", lambda *a, **k: called.append("x"))
    add_rounds(store, 0, A, 20, 20, 1)
    add_rounds(store, 1, B, 60, 20, 2)
    watcher(store, mandate)._judge([A, B], 1, 0)  # pyright: ignore[reportPrivateUsage]
    assert called == [] and len(active(store)) == 1


def test_a_deploy_too_short_to_judge_is_skipped_as_baseline(store: Store, mandate: Mandate) -> None:
    add_rounds(store, 0, A, 20, 20, 1)
    add_rounds(store, 1, B, 20, 4, 2)  # replaced by the next deploy after four rounds
    add_rounds(store, 2, C, 8, 20, 3)
    assert watcher(store, mandate)._baseline([A, B, C]) == 0  # pyright: ignore[reportPrivateUsage]


def test_a_version_deployed_again_starts_its_own_window(store: Store, mandate: Mandate) -> None:
    """After a rollback to B, B's earlier rounds must not count for the new deploy of B."""
    add_rounds(store, 0, A, 20, 20, 1)
    add_rounds(store, 1, B, 5, 40, 2)  # B's first deploy, long and fast
    store.set_value("outage_deploy:2", "x")  # C was an outage, rolled back
    add_rounds(store, 3, B, 5, 4, 3)  # B again: only four rounds so far
    w = watcher(store, mandate)
    assert w._baseline([A, B, C, B]) == 1  # pyright: ignore[reportPrivateUsage]
    w._judge([A, B, C, B], 3, 1)  # pyright: ignore[reportPrivateUsage]
    assert verdict(store, f"3:{B}") is None  # waits for its own rounds


def test_an_endpoint_the_probe_user_may_not_read_does_not_block_the_verdict(store: Store, mandate: Mandate) -> None:
    add_rounds(store, 0, A, 20, 20, 1)
    add_rounds(store, 1, B, 20, 20, 2)
    for deploy, version in ((0, A), (1, B)):
        for _ in range(20):
            store.add_round("GET /admin/", version, [403] * 5, [1.0] * 5, deploy=deploy)
    watcher(store, mandate)._judge([A, B], 1, 0)  # pyright: ignore[reportPrivateUsage]
    judged = verdict(store, f"1:{B}")
    assert judged is not None and judged.impact.value == "healthy"
    assert [e["target"] for e in judged.endpoints] == ["GET /items/"]


@pytest.fixture
def history_repo(tmp_path: Path) -> tuple[Path, list[str]]:
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    shas: list[str] = []
    for i in range(3):
        (tmp_path / "f").write_text(str(i))
        subprocess.run([*git, "add", "."], check=True)
        subprocess.run([*git, "commit", "-qm", f"c{i}"], check=True)
        shas.append(subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip())
    return tmp_path, shas


def ledger_entry(store: Store, index: int, commit: str, status: str = "verified", by: str = "unbidden") -> None:
    store.put(
        "deployments",
        Deployment(
            id=str(index),
            index=index,
            environment="local-compose",
            containers=[],
            commit=commit,
            commit_status=status,  # type: ignore[arg-type]
            commit_reason="test",
            initiated_by=by,  # type: ignore[arg-type]
        ),
    )


def merged_change(store: Store, base: str, merge: str) -> Opportunity:
    opp = Opportunity(
        source="world",
        category="performance",
        title="t",
        summary="s",
        dedup_key="k",
        evidence=[EvidenceRef(kind="file", locator="x")],
        evidence_level=EvidenceLevel.FUNCTIONAL_VALIDATION,
        status=OpportunityStatus.PROPOSED,
        details={"endpoints": ["GET /items/"]},
    )
    store.put("opportunities", opp)
    store.put(
        "proposals",
        Proposal(
            opportunity_id=opp.id,
            experiment_id="e",
            branch="unbidden/x",
            base_sha=base,
            commit_sha="f" * 40,
            merge_sha=merge,
            title="t",
            body_md="b",
            evidence_level=EvidenceLevel.FUNCTIONAL_VALIDATION,
            status=ProposalStatus.MERGED,
        ),
    )
    return opp


def outcome_of(store: Store, opp: Opportunity) -> tuple[EvidenceLevel, dict[str, Any]]:
    stored = store.get("opportunities", opp.id, Opportunity)
    assert stored is not None
    return stored.evidence_level, stored.details["outcome"]


def test_level_5_only_on_the_first_deploy_of_a_merged_change(
    store: Store, mandate: Mandate, history_repo: tuple[Path, list[str]]
) -> None:
    repo, (v0, v1, _v2) = history_repo
    opp = merged_change(store, v0, v1)
    ledger_entry(store, 0, v0)
    ledger_entry(store, 1, v1)
    add_rounds(store, 0, v0, 20, 20, 1)
    add_rounds(store, 1, v1, 5, 20, 2)
    watcher(store, mandate, repo)._judge([v0, v1], 1, 0)  # pyright: ignore[reportPrivateUsage]
    level, outcome = outcome_of(store, opp)
    assert level is EvidenceLevel.OPERATIONAL_RESULT
    assert outcome["baseline"] == f"0:{v0}" and outcome["result"] == "positive"
    assert outcome["criteria"]["criteria_version"] == "v2"
    assert {c["kind"] for c in outcome["confounders"]} >= {"commits_between", "synthetic_traffic"}


def test_no_level_5_when_the_running_version_was_only_inferred(
    store: Store, mandate: Mandate, history_repo: tuple[Path, list[str]]
) -> None:
    """The same improvement, but the candidate's commit is HEAD when first seen: nothing proves it ran v1."""
    repo, (v0, v1, _v2) = history_repo
    opp = merged_change(store, v0, v1)
    ledger_entry(store, 0, v0)
    ledger_entry(store, 1, v1, status="inferred", by="external")
    add_rounds(store, 0, v0, 20, 20, 1)
    add_rounds(store, 1, v1, 5, 20, 2)
    watcher(store, mandate, repo)._judge([v0, v1], 1, 0)  # pyright: ignore[reportPrivateUsage]
    level, outcome = outcome_of(store, opp)
    assert level is EvidenceLevel.FUNCTIONAL_VALIDATION
    assert outcome["result"] == "invalid"
    assert any("inferred" in w for w in outcome["why"]) and any("not made by Unbidden" in w for w in outcome["why"])
    assert {"kind": "external_deploy", "detail": "deploy 1"} in outcome["confounders"]


def test_no_level_5_for_deploys_recorded_before_the_ledger(
    store: Store, mandate: Mandate, history_repo: tuple[Path, list[str]]
) -> None:
    repo, (v0, v1, _v2) = history_repo
    opp = merged_change(store, v0, v1)
    add_rounds(store, 0, v0, 20, 20, 1)
    add_rounds(store, 1, v1, 5, 20, 2)
    watcher(store, mandate, repo)._judge([v0, v1], 1, 0)  # pyright: ignore[reportPrivateUsage]
    level, outcome = outcome_of(store, opp)
    assert level is EvidenceLevel.FUNCTIONAL_VALIDATION and outcome["result"] == "invalid"
    judged = verdict(store, f"1:{v1}")
    assert judged is not None and judged.commits == {"0": "no ledger record", "1": "no ledger record"}


def test_an_unchanged_latency_is_inconclusive_not_negative(
    store: Store, mandate: Mandate, history_repo: tuple[Path, list[str]]
) -> None:
    repo, (v0, v1, _v2) = history_repo
    opp = merged_change(store, v0, v1)
    ledger_entry(store, 0, v0)
    ledger_entry(store, 1, v1)
    add_rounds(store, 0, v0, 20, 20, 1)
    add_rounds(store, 1, v1, 20, 20, 2)
    watcher(store, mandate, repo)._judge([v0, v1], 1, 0)  # pyright: ignore[reportPrivateUsage]
    level, outcome = outcome_of(store, opp)
    assert level is EvidenceLevel.FUNCTIONAL_VALIDATION and outcome["result"] == "inconclusive"


def test_a_degraded_deploy_carries_the_scope_of_what_degraded(store: Store, mandate: Mandate) -> None:
    world = WorldModel(rev=A)
    ev = [EvidenceRef(kind="config", locator="x")]
    world.add(
        Resource(id="endpoint:GET /items/", kind="endpoint", name="GET /items/", status=OBS, confidence=1, evidence=ev)
    )
    world.add(Resource(id="service:api", kind="service", name="api", status=OBS, confidence=1, evidence=ev))
    world.relate(
        Relation(
            src="service:api", dst="endpoint:GET /items/", predicate="serves", status=OBS, confidence=1, evidence=ev
        )
    )
    add_rounds(store, 0, A, 20, 20, 1)
    add_rounds(store, 1, B, 60, 20, 2)
    LiveWatcher(Path("."), store, mandate, world, log=lambda _: None)._judge([A, B], 1, 0)  # pyright: ignore[reportPrivateUsage]
    judged = verdict(store, f"1:{B}")
    assert judged is not None and judged.impact.value == "degraded"
    components = [c["id"] for c in judged.scope[0]["components"]]
    assert components == ["endpoint:GET /items/", "service:api"]
    assert any(b.startswith("metrics:") for b in judged.scope[0]["blind_spots"])
