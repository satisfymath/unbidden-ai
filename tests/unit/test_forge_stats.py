from __future__ import annotations

import random

import pytest

from unbidden.forge.stats import CapabilityCard, StatsAdapter, admit, deltas, known_format, oracle, read

pytestmark = pytest.mark.unit

GOOD_LINE = r"(?P<name>[A-Za-z0-9_.:-]+): (?P<value>\d+(\.\d+)?)"
GOOD_ENTITY = r"cluster\.(?P<entity>[A-Za-z0-9_-]+)\.(?P<metric>[A-Za-z0-9_.]+)"


def envoy_like(seed: int, n: int = 300) -> list[str]:
    rng = random.Random(seed)
    clusters = ["frontend", "flagservice", "image-provider", "flagd-ui", "chatbot"]
    metrics = ["upstream_rq_5xx", "upstream_rq_completed", "upstream_cx_active", "membership_healthy"]
    lines = [f"cluster.{rng.choice(clusters)}.{rng.choice(metrics)}: {rng.randint(0, 50000)}" for _ in range(n)]
    lines += [f"server.memory_allocated: {rng.randint(10**6, 10**8)}", "server.uptime: 3600"]
    return lines


def card() -> CapabilityCard:
    return CapabilityCard(
        purpose="t", kind="stats", input={}, output={}, permissions=["runtime.read"], data_sources=[], privacy="t"
    )


def test_a_structural_spec_passes_the_oracle_on_unseen_lines() -> None:
    result = oracle(GOOD_LINE, GOOD_ENTITY, envoy_like(2))
    assert result.passed, result.problems
    assert result.coverage == 1.0


def test_a_spec_that_memorized_values_fails_the_metamorphic_check() -> None:
    lines = envoy_like(3)
    seen = "|".join(sorted({ln.rsplit(": ", 1)[1] for ln in lines}))
    result = oracle(rf"(?P<name>[A-Za-z0-9_.:-]+): (?P<value>{seen})", None, lines)
    assert not result.passed and any("changed value" in p for p in result.problems)


def test_admission_refuses_hangs_and_wrong_groups() -> None:
    assert admit(r"(?P<name>(a+)+): (?P<value>\d+)", None)
    assert admit(r"(?P<name>\S+) (?P<n>\d+)", None)
    assert admit(GOOD_LINE, GOOD_ENTITY) == []


def test_a_known_format_is_not_built_again() -> None:
    prometheus = ["# HELP up Whether up", "# TYPE up gauge", 'up{job="a"} 1', "process_cpu_seconds_total 12.5"] * 5
    assert known_format(prometheus) == "prometheus-text"
    assert known_format(envoy_like(1)) is None


def test_counters_are_compared_between_snapshots_per_entity() -> None:
    adapter = StatsAdapter(source="s", version=1, line=GOOD_LINE, entity=GOOD_ENTITY, card=card())
    before = ["cluster.frontend.upstream_rq_5xx: 24", "cluster.image-provider.upstream_rq_5xx: 0"]
    after = ["cluster.frontend.upstream_rq_5xx: 31", "cluster.image-provider.upstream_rq_5xx: 0"]
    assert deltas(adapter, before, after, "upstream_rq_5xx") == {"frontend": 7.0, "image-provider": 0.0}
    assert read(adapter, ["cluster.frontend.upstream_rq_5xx: x"]) == []
