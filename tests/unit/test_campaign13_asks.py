"""The campaign 13 harness answers the agent's questions only by the protocol's table (PROTOCOL.md §7)."""

from __future__ import annotations

import pytest

from bench.campaign13.asks import FINAL_CAP_USD, Policy

pytestmark = pytest.mark.unit


def _ask(kind: str, *options: str, title: str = "t") -> dict[str, object]:
    return {"id": f"ask_{kind}", "kind": kind, "title": title, "options": [{"key": o} for o in options]}


def test_the_table_and_nothing_else() -> None:
    lab = Policy(mode="autonomous", lab=True, credentials={"MODEL_API_KEY": "k"})
    plain = Policy(mode="autopilot", lab=False)
    assert (
        lab.decide(_ask("registry", "allow", "later", title="Allow the sandbox to reach deb.debian.org?"))[0] == "allow"
    )
    assert (
        lab.decide(_ask("registry", "allow", "later", title="Allow the sandbox to reach evil.example?"))[0] == "later"
    )
    assert lab.decide(_ask("credential", "set", "later")) == ("set", "k", "the campaign's model key")
    assert plain.decide(_ask("credential", "set", "later"))[0] == "later"
    assert plain.decide(_ask("approval", "approve", "reject", "later"))[0] == "approve"
    assert lab.decide(_ask("approval", "approve", "reject", "later"))[0] == "later"
    assert (
        lab.decide(_ask("drill", "run", "later"))[0] == "run"
        and plain.decide(_ask("drill", "run", "later"))[0] == "later"
    )
    assert lab.decide(_ask("spend", "raise", "later"))[:2] == ("raise", f"{FINAL_CAP_USD:.2f}")
    assert lab.decide(_ask("hold", "keep", "release"))[0] == "keep"
    assert lab.decide(_ask("resume", "resume", "later"))[0] == "later"  # the kill switch is a person's
    assert lab.decide(_ask("ledger", "later"))[0] == "later"
