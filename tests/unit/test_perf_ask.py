"""What the perf lab sends to the model, and what it records when no answer comes (stage 8 regression, B-4).

Found on Conduit (37e2324 → 6bbf3a1): every workload request was refused by Guardian's prompt scan, because the
tests shown as examples log in with `password="password"`; the lab swallowed the refusal and recorded `()`."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from unbidden.brain.router import PolicyDenied
from unbidden.guardian.scanner import scan_many, secret_hits
from unbidden.lab.perf import PerfLab

pytestmark = pytest.mark.unit
EXAMPLE = 'user = await repo.create_user(username="u", email="u@example.test", password="password")\n'


class Brain:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[str] = []
        self.fail = fail

    async def complete(self, request: Any) -> Any:
        self.sent.append(request.messages[0].content)
        if self.fail:
            raise PolicyDenied("refused")
        return SimpleNamespace(content="# file: .unbidden-lab/workload.py\n```python\nx = 1\n```\n")


def ask(brain: Brain, notes: list[str]) -> Any:
    lab = SimpleNamespace(brain=brain)
    opp = SimpleNamespace(id="opp_1")
    return asyncio.run(PerfLab._ask_files(lab, "lab.workload", "tests:\n" + EXAMPLE, opp, "sha", 100, notes))  # type: ignore[arg-type]


def test_credential_looking_values_are_masked_and_the_prompt_passes_the_scan() -> None:
    assert secret_hits(scan_many([EXAMPLE]))  # the guard would refuse the text as it is
    brain, notes = Brain(), []
    ask(brain, notes)
    (sent,) = brain.sent
    assert not secret_hits(scan_many([sent])) and 'password="password"' not in sent
    assert any("masked" in n for n in notes)


def test_a_refused_request_is_recorded_not_swallowed() -> None:
    notes: list[str] = []
    assert ask(Brain(fail=True), notes) is None
    assert any(n.startswith("lab.workload: no answer (PolicyDenied: refused") for n in notes)
