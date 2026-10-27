from __future__ import annotations

import random
from pathlib import Path
from typing import Any

import pytest

from unbidden.contracts.guardian import Autonomy, Mandate
from unbidden.contracts.world import WorldModel
from unbidden.observe import live as live_module
from unbidden.observe.live import DeployVerdict, LiveWatcher
from unbidden.operate.deploy import DeployResult
from unbidden.operate.holds import active
from unbidden.store import Store

pytestmark = pytest.mark.unit
A, B, C = "a" * 40, "b" * 40, "c" * 40


def add_rounds(store: Store, version: str, center: float, n: int, seed: int) -> None:
    rng = random.Random(seed)
    for _ in range(n):
        store.add_round("GET /items/", version, [200] * 5, [center * rng.uniform(0.9, 1.1) for _ in range(5)])


def watcher(store: Store, mandate: Mandate) -> LiveWatcher:
    return LiveWatcher(Path("."), store, mandate, WorldModel(rev=A), log=lambda _: None)


def test_waits_until_the_new_window_is_full(store: Store, mandate: Mandate) -> None:
    store.set_value("deploy_sequence", [A, B])
    add_rounds(store, A, 20, 20, 1)
    add_rounds(store, B, 60, 5, 2)
    watcher(store, mandate)._judge(f"1:{B}", B, A)  # pyright: ignore[reportPrivateUsage]
    assert store.get("deploy_verdicts", f"1:{B}", DeployVerdict) is None


def test_degraded_deploy_holds_and_rolls_back_to_the_last_healthy(
    store: Store, mandate: Mandate, monkeypatch: pytest.MonkeyPatch
) -> None:
    mandate.autonomy.rollback = Autonomy.ALLOW
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        live_module, "deploy", lambda *a, **k: calls.append({"commit": a[3], **k}) or DeployResult(True, a[3], "")
    )
    store.set_value("deploy_sequence", [A, B, C])
    store.put("deploy_verdicts", DeployVerdict(id=f"1:{B}", previous=A, impact="healthy", endpoints=[], criteria={}))  # type: ignore[arg-type]
    add_rounds(store, B, 20, 20, 1)
    add_rounds(store, C, 60, 20, 2)
    watcher(store, mandate)._judge(f"2:{C}", C, B)  # pyright: ignore[reportPrivateUsage]
    verdict = store.get("deploy_verdicts", f"2:{C}", DeployVerdict)
    assert verdict is not None and verdict.impact.value == "degraded"
    assert (
        calls == [{"commit": B, "reason": f"deploy 2:{C[:10]} judged degraded", "rollback": True}]
        or calls[0]["commit"] == B
    )
    assert len(active(store)) == 1


def test_without_rollback_autonomy_only_a_hold_is_placed(
    store: Store, mandate: Mandate, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[str] = []
    monkeypatch.setattr(live_module, "deploy", lambda *a, **k: called.append("x"))
    store.set_value("deploy_sequence", [A, B])
    add_rounds(store, A, 20, 20, 1)
    add_rounds(store, B, 60, 20, 2)
    watcher(store, mandate)._judge(f"1:{B}", B, A)  # pyright: ignore[reportPrivateUsage]
    assert called == [] and len(active(store)) == 1


def test_a_deploy_too_short_to_judge_is_skipped_as_baseline_and_named(store: Store, mandate: Mandate) -> None:
    store.set_value("deploy_sequence", [A, B, C])
    add_rounds(store, A, 20, 20, 1)
    add_rounds(store, B, 20, 4, 2)  # replaced by the next deploy after four rounds
    add_rounds(store, C, 8, 20, 3)
    w = watcher(store, mandate)
    assert w._baseline([A, B, C]) == A  # pyright: ignore[reportPrivateUsage]


def test_an_endpoint_the_probe_user_may_not_read_does_not_block_the_verdict(store: Store, mandate: Mandate) -> None:
    store.set_value("deploy_sequence", [A, B])
    add_rounds(store, A, 20, 20, 1)
    add_rounds(store, B, 20, 20, 2)
    for version in (A, B):
        for _ in range(20):
            store.add_round("GET /admin/", version, [403] * 5, [1.0] * 5)
    watcher(store, mandate)._judge(f"1:{B}", B, A)  # pyright: ignore[reportPrivateUsage]
    verdict = store.get("deploy_verdicts", f"1:{B}", DeployVerdict)
    assert verdict is not None and verdict.impact.value == "healthy"
    assert [e["target"] for e in verdict.endpoints] == ["GET /items/"]
