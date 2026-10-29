from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_router import make_brain, request
from unbidden.brain.providers import ProviderError, ProviderThrottled
from unbidden.brain.router import PolicyDenied, SpendLimitReached
from unbidden.brain.spend import Budget, SpendLedger, SpendRefused, summarize, worst_cost
from unbidden.contracts.common import utc_now
from unbidden.contracts.guardian import EgressAttempt, Mandate
from unbidden.contracts.llm import LLMRequest, LLMResponse, Tier, Usage
from unbidden.store import Store

pytestmark = pytest.mark.unit


def verified(ledger: SpendLedger, remaining: float, **kwargs: Any) -> None:
    ledger.set_budget(Budget(remaining_usd=remaining, verified_at=utc_now(), source="test dashboard", **kwargs))


def reserve(ledger: SpendLedger, usd: float, **kwargs: Any) -> str:
    return ledger.reserve(
        est_usd=usd, workspace="w", purpose="p", provider="meta", model="muse-spark-1.3", attempt=1, **kwargs
    )


def test_without_a_verified_balance_only_the_allowance_is_spent(spend_home: Path) -> None:
    ledger = SpendLedger()
    status = ledger.status()
    assert not status.verified and status.permitted_usd == 1.0
    reserve(ledger, 0.6)
    with pytest.raises(SpendRefused, match="left of"):
        reserve(ledger, 0.6)


def test_the_reserve_is_held_back_until_a_person_releases_it(spend_home: Path) -> None:
    ledger = SpendLedger()
    verified(ledger, 100.0)
    assert ledger.status().permitted_usd == pytest.approx(80.0)
    reserve(ledger, 79.0)
    with pytest.raises(SpendRefused, match=r"reserve US\$20\.00"):
        reserve(ledger, 2.0)
    verified(ledger, 100.0, reserve_released=True)
    # A new verification starts counting again from its own time; spend before it is in the balance read.
    reserve(ledger, 2.0)


def test_spend_counts_from_the_verification_not_before(spend_home: Path) -> None:
    ledger = SpendLedger()
    reserve(ledger, 0.9)
    verified(ledger, 10.0)
    assert ledger.status().spent_usd == 0.0
    assert ledger.status().available_usd == pytest.approx(8.0)


def test_expired_credits_refuse_everything(spend_home: Path) -> None:
    ledger = SpendLedger()
    verified(ledger, 100.0, expires_at=utc_now() - timedelta(minutes=1))
    with pytest.raises(SpendRefused, match="expired"):
        reserve(ledger, 0.01)


def test_settled_cost_replaces_the_reservation_and_unknown_keeps_the_worst(spend_home: Path) -> None:
    ledger = SpendLedger()
    a = reserve(ledger, 0.5)
    b = reserve(ledger, 0.3)
    ledger.settle(a, usd=0.01, tokens_in=100, tokens_out=50, usage_reported=True)
    ledger.settle(b, usd=None, usage_reported=False, status="failed", note="timeout")
    assert ledger.status().spent_usd == pytest.approx(0.31)
    by_model = summarize(ledger.rows(), "model")["muse-spark-1.3"]
    assert by_model["calls"] == 2 and by_model["failed"] == 1 and by_model["unreported"] == 1


def test_a_shared_ledger_bounds_every_workspace_together(spend_home: Path) -> None:
    first, second = SpendLedger(), SpendLedger()
    reserve(first, 0.7)
    with pytest.raises(SpendRefused):
        reserve(second, 0.7)


def test_calls_are_attributed_to_the_run(spend_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNBIDDEN_RUN", "bench:pilot:rich")
    ledger = SpendLedger()
    reserve(ledger, 0.1)
    assert ledger.rows(run="bench:pilot:rich")[0]["workspace"] == "w"


def test_worst_cost_counts_every_byte_and_the_whole_output() -> None:
    assert worst_cost(1000, 1000, 1.25, 4.25) == pytest.approx((1064 * 1.25 + 1000 * 4.25) / 1e6)


async def test_the_router_refuses_before_sending_when_the_budget_is_spent(store: Store, mandate: Mandate) -> None:
    brain, _, remote = make_brain(store, mandate)
    brain.spend.set_budget(Budget(unverified_allowance_usd=0.0))
    with pytest.raises(SpendLimitReached, match="refused"):
        await brain.complete(request(Tier.FRONTIER, text="hello"))
    assert remote.requests == []


async def test_the_router_settles_reported_usage(store: Store, mandate: Mandate) -> None:
    brain, _, remote = make_brain(store, mandate)
    remote.script("bridge.solve", "ok")
    await brain.complete(request(Tier.FRONTIER, text="hello"))
    (row,) = brain.spend.rows()
    assert row["status"] == "settled" and row["usage_reported"] == 1
    assert row["usd"] == pytest.approx((100 * 1.25 + 20 * 4.25) / 1e6)
    assert row["usd"] < row["est_usd"]


async def test_an_answer_without_usage_keeps_its_worst_cost(store: Store, mandate: Mandate) -> None:
    brain, _, remote = make_brain(store, mandate)
    remote.script("bridge.solve", LLMResponse(content="ok", done_reason="stop", usage=Usage()))
    await brain.complete(request(Tier.FRONTIER, text="hello"))
    (row,) = brain.spend.rows()
    assert row["usd"] == row["est_usd"] and row["usage_reported"] == 0


async def test_a_throttled_call_costs_nothing_and_a_failed_one_its_worst(store: Store, mandate: Mandate) -> None:
    brain, _, remote = make_brain(store, mandate)

    def throttled(_: LLMRequest) -> LLMResponse:
        raise ProviderThrottled("429")

    def broken(_: LLMRequest) -> LLMResponse:
        raise ProviderError("502")

    remote.script("bridge.solve", throttled, broken)
    for _ in range(2):
        with pytest.raises(ProviderError):
            await brain.complete(request(Tier.FRONTIER, text="hello"))
    first, second = brain.spend.rows()
    assert first["status"] == "failed" and first["usd"] == 0.0
    assert second["status"] == "failed" and second["usd"] == second["est_usd"]


async def test_a_payload_the_egress_gate_blocks_reserves_nothing(store: Store, mandate: Mandate) -> None:
    from unbidden.brain.router import EgressBlocked
    from unbidden.guardian.scanner import SensitiveTermIndex

    brain, local, _ = make_brain(store, mandate, identifiers=SensitiveTermIndex(["acme_billing"]))
    local.script("bridge.solve", "ok")
    with pytest.raises(EgressBlocked):
        await brain._complete_on(  # pyright: ignore[reportPrivateUsage]
            Tier.FRONTIER, request(Tier.FRONTIER, text="fix acme_billing"), None, *brain.decide(request(Tier.FRONTIER))
        )
    (row,) = brain.spend.rows()
    assert row["status"] == "released" and row["charged"] == 0
    assert store.list("egress", EgressAttempt)[0].status == "blocked"


async def test_contributor_models_are_refused_unless_a_person_allows_them(store: Store, mandate: Mandate) -> None:
    brain, _, remote = make_brain(store, mandate)
    brain.config.routing[Tier.FRONTIER].model = "muse-spark-1.3-contributor"
    brain.config.routing[Tier.CODE].model = "muse-spark-1.3-contributor"
    brain.config.prices.models["muse-spark-1.3-contributor"] = brain.config.prices.models["muse-spark-1.3"]
    with pytest.raises(PolicyDenied, match="contributor"):
        await brain._complete_on(  # pyright: ignore[reportPrivateUsage]
            Tier.FRONTIER, request(Tier.FRONTIER, text="hello"), None, *brain.decide(request(Tier.FRONTIER))
        )
    assert remote.requests == []


async def test_a_remote_model_without_a_price_is_refused(store: Store, mandate: Mandate) -> None:
    brain, _, remote = make_brain(store, mandate)
    brain.config.routing[Tier.FRONTIER].model = "muse-spark-9"
    with pytest.raises(PolicyDenied, match="no price"):
        await brain._complete_on(  # pyright: ignore[reportPrivateUsage]
            Tier.FRONTIER, request(Tier.FRONTIER, text="hello"), None, *brain.decide(request(Tier.FRONTIER))
        )
    assert remote.requests == []


def test_envelopes_refuse_a_call_that_names_none_or_would_not_fit_and_amending_keeps_earlier_spend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stage 9: US$30 more split into development, evaluation and demo envelopes, enforced before each call; the
    cap amended without moving the verification, so what was spent before still counts."""
    from datetime import UTC, datetime, timedelta

    from unbidden.brain.spend import Budget, SpendLedger, SpendRefused

    ledger = SpendLedger(tmp_path)
    ledger.set_budget(Budget(remaining_usd=10.0, verified_at=datetime.now(UTC) - timedelta(days=1), source="s",
                             reserve_fraction=0.0))  # fmt: skip
    monkeypatch.delenv("UNBIDDEN_ENVELOPE", raising=False)
    earlier = ledger.reserve(est_usd=7.0, workspace="w", purpose="p", provider="meta", model="m", attempt=1)
    ledger.settle(earlier, usd=7.0, usage_reported=True)
    amended = ledger.budget().model_copy(
        update={
            "remaining_usd": 37.0,
            "envelopes": {"dev": 2.0, "eval": 1.0},
            "envelopes_total_usd": 30.0,
            "envelopes_since": datetime.now(UTC),
        }
    )
    ledger.set_budget(amended)
    assert round(ledger.status().spent_usd, 4) == 7.0  # earlier spend still counts against the cumulative cap
    with pytest.raises(SpendRefused, match="UNBIDDEN_ENVELOPE"):
        ledger.reserve(est_usd=0.1, workspace="w", purpose="p", provider="meta", model="m", attempt=1)
    monkeypatch.setenv("UNBIDDEN_ENVELOPE", "eval")
    first = ledger.reserve(est_usd=0.8, workspace="w", purpose="p", provider="meta", model="m", attempt=1)
    with pytest.raises(SpendRefused, match="envelope 'eval'"):
        ledger.reserve(est_usd=0.3, workspace="w", purpose="p", provider="meta", model="m", attempt=1)
    ledger.settle(first, usd=0.5, usage_reported=True)  # reconciled to the observed cost: room again
    ledger.reserve(est_usd=0.3, workspace="w", purpose="p", provider="meta", model="m", attempt=1)
    monkeypatch.setenv("UNBIDDEN_ENVELOPE", "dev")
    ledger.reserve(est_usd=1.9, workspace="w", purpose="p", provider="meta", model="m", attempt=1)
    assert round(ledger.envelope_spent("eval"), 4) == 0.8 and round(ledger.envelope_spent("dev"), 4) == 1.9
