from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from unbidden.observe.logs import detect, normalize, parse_line, summarize_window

pytestmark = pytest.mark.unit
T0 = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def at(minutes: float) -> str:
    return (T0 + timedelta(minutes=minutes)).isoformat()


def test_lines_of_one_kind_share_a_shape_whatever_their_values() -> None:
    a = normalize("user 42 failed to load order 3f2a9c1e5b7d after 120 ms from 10.0.0.7")
    b = normalize("user 7 failed to load order 9b8c7d6e5f4a after 33 ms from 10.0.0.9")
    assert a == b


def test_a_line_is_redacted_before_it_is_read() -> None:
    parsed = parse_line('2026-10-27T12:00:01Z ERROR login failed password="hunter2-secret-value" for admin')
    assert parsed.level == "error" and "hunter2-secret-value" not in parsed.message


def test_json_lines_give_level_and_status() -> None:
    parsed = parse_line('{"level": 50, "msg": "charge failed", "statusCode": 502}')
    assert (parsed.level, parsed.status, parsed.message) == ("error", 502, "charge failed")


def test_a_new_error_after_a_deploy_is_a_correlation_signal_and_steady_noise_is_not_acted_on() -> None:
    before = [summarize_window("api", [f"{at(i)} INFO GET /items 200"] * 60, received=T0) for i in range(3)]
    after = summarize_window(
        "api",
        [f"{at(30)} ERROR KeyError: 'owner' in handler"] * 5 + [f"{at(30)} INFO GET /items 200"] * 60,
        received=T0,
    )
    signals = detect([*before, after], deploy_at=T0 + timedelta(minutes=20), deploy="3103525")
    assert [s.kind for s in signals] == ["error_after_deploy"]
    assert "not a cause" in signals[0].summary

    steady = [summarize_window("api", [f"{at(i)} ERROR cache miss storm"] * 4, received=T0) for i in range(14)]
    assert [s.kind for s in detect(steady)] == ["noise"]


def test_a_rise_in_the_share_of_5xx_is_measured_against_earlier_windows() -> None:
    calm = [summarize_window("api", ['"GET /x HTTP/1.1" 200'] * 100, received=T0) for _ in range(4)]
    bad = summarize_window("api", ['"GET /x HTTP/1.1" 500'] * 10 + ['"GET /x HTTP/1.1" 200'] * 90, received=T0)
    kinds = [s.kind for s in detect([*calm, bad])]
    assert "error_rate_increase" in kinds


def test_lines_beyond_the_budget_are_counted_not_silently_lost() -> None:
    from unbidden.observe.logs import MAX_LINES

    window = summarize_window("api", ["INFO x"] * (MAX_LINES + 7), received=T0)
    assert window["dropped"] == 7 and window["lines"] == MAX_LINES
