from __future__ import annotations

import pytest

from unbidden.forge.adapter import admit, oracle

pytestmark = pytest.mark.unit

LINES = [f'INFO:     127.0.0.1:{40000 + i} - "GET /api/v1/items/ HTTP/1.1" 200 OK' for i in range(30)]
GOOD = r'"(?P<method>[A-Z]+) (?P<path>/\S*) HTTP/[\d.]+" (?P<status>\d{3})'


def test_admission_refuses_dangerous_or_incomplete_patterns() -> None:
    assert admit(GOOD) == []
    assert any("backreference" in p for p in admit(r"(?P<method>\w+)\1 (?P<path>\S+) (?P<status>\d+)"))
    assert any("nests" in p for p in admit(r"(?P<method>(a+)+) (?P<path>\S+) (?P<status>\d+)"))
    assert any("needs the fields" in p for p in admit(r"(?P<method>\w+)"))
    assert any("unknown fields" in p for p in admit(GOOD + r"(?P<user>\w+)"))


def test_oracle_accepts_a_general_adapter() -> None:
    result = oracle(GOOD, LINES)
    assert result.passed and result.coverage == 1.0


def test_oracle_refuses_an_adapter_fitted_to_the_statuses_it_saw() -> None:
    fitted = r'"(?P<method>[A-Z]+) (?P<path>/\S*) HTTP/[\d.]+" (?P<status>200|403|404)'
    result = oracle(fitted, LINES)
    assert not result.passed and any("status 500" in p for p in result.problems)


def test_oracle_needs_enough_unseen_lines() -> None:
    assert not oracle(GOOD, LINES[:5]).passed


def test_what_a_remote_model_sees_of_a_log_has_no_real_paths_or_addresses() -> None:
    from unbidden.forge.build import log_transform

    lines = ['INFO:     10.1.2.3:50000 - "GET /api/v1/invoices/ledger?x=1 HTTP/1.1" 200 OK']
    transform = log_transform(lines)
    seen = transform.apply(lines[0])
    assert "invoices" not in seen and "ledger" not in seen and "10.1.2.3" not in seen
    assert '"GET /' in seen and "HTTP/1.1" in seen and " 200 " in seen  # the structure survives
    quoted = transform.apply("expected path=/api/v1/invoices/ledger status=200")
    assert "invoices" not in quoted and "ledger" not in quoted
