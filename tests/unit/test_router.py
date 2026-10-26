from __future__ import annotations

from typing import Any

import pytest

from unbidden.brain.providers.mock import MockProvider
from unbidden.brain.router import (
    Brain,
    EgressBlocked,
    KillSwitchEngaged,
    ModelFailed,
    SecretInPrompt,
    SpendLimitReached,
)
from unbidden.config import load_config
from unbidden.contracts.events import EventType
from unbidden.contracts.guardian import EgressAttempt, Mandate
from unbidden.contracts.llm import LLMRequest, LLMResponse, Message, ModelRun, Tier, ToolCall, ToolSpec, Usage
from unbidden.guardian.killswitch import KillSwitch
from unbidden.guardian.scanner import SensitiveTermIndex
from unbidden.store import Store

pytestmark = pytest.mark.unit

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"verdict": {"type": "string", "enum": ["fix", "skip"]}},
    "required": ["verdict"],
    "additionalProperties": False,
}


class RemoteMock(MockProvider):
    host = "api.meta.ai"


def make_brain(store: Store, mandate: Mandate, **kwargs: Any) -> tuple[Brain, MockProvider, RemoteMock]:
    config = load_config()
    config.routing[Tier.LOCAL].provider = "local"
    config.routing[Tier.FRONTIER].provider = "remote"
    local, remote = MockProvider(), RemoteMock()
    brain = Brain(config, {"local": local, "remote": remote}, store, mandate, **kwargs)
    return brain, local, remote


def request(tier: Tier = Tier.LOCAL, text: str = "decide", **kwargs: Any) -> LLMRequest:
    return LLMRequest(purpose="test.decide", tier=tier, messages=[Message(role="user", content=text)], **kwargs)


async def test_valid_json_on_first_attempt(store: Store, mandate: Mandate) -> None:
    brain, local, _ = make_brain(store, mandate)
    local.script("test.decide", {"verdict": "fix"})
    value, _ = await brain.complete_json(request(response_schema=SCHEMA))
    assert value == {"verdict": "fix"}
    runs = store.list("model_runs", ModelRun)
    assert [r.ok for r in runs] == [True]


async def test_schema_problem_is_explained_and_repaired(store: Store, mandate: Mandate) -> None:
    brain, local, _ = make_brain(store, mandate)
    local.script("test.decide", {"verdict": "maybe"}, '```json\n{"verdict": "skip"}\n```')
    value, _ = await brain.complete_json(request(response_schema=SCHEMA))
    assert value == {"verdict": "skip"}
    retry = local.requests[1].messages[-1].content
    assert "rejected" in retry and "verdict" in retry


async def test_gives_up_after_the_repair_budget(store: Store, mandate: Mandate) -> None:
    brain, local, _ = make_brain(store, mandate)
    local.script("test.decide", "not json", repeat=True)
    with pytest.raises(ModelFailed):
        await brain.complete(request(response_schema=SCHEMA))
    assert len(local.requests) == 2


async def test_truncated_answer_doubles_the_budget(store: Store, mandate: Mandate) -> None:
    brain, local, _ = make_brain(store, mandate)
    local.script(
        "test.decide",
        LLMResponse(content='{"verd', done_reason="length", usage=Usage()),
        {"verdict": "fix"},
    )
    await brain.complete(request(response_schema=SCHEMA, max_tokens=100))
    assert local.requests[1].max_tokens == 2 * local.requests[0].max_tokens


async def test_required_tool_and_argument_validation(store: Store, mandate: Mandate) -> None:
    brain, local, _ = make_brain(store, mandate)
    tool = ToolSpec(
        name="finish",
        description="done",
        parameters={"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]},
    )
    local.script(
        "test.decide",
        "I am done",
        ToolCall(name="finish", arguments={"n": "x"}),
        ToolCall(name="finish", arguments={"n": 1}),
    )
    brain.config.brain.max_repairs = 2
    response = await brain.complete(request(tools=[tool], tool_choice="required"))
    assert response.tool_calls[0].arguments == {"n": 1}


async def test_secret_in_prompt_never_reaches_a_model(store: Store, mandate: Mandate) -> None:
    brain, local, _ = make_brain(store, mandate)
    with pytest.raises(SecretInPrompt):
        await brain.complete(request(text="use DB_PASSWORD=hunter2hunter2"))
    assert local.requests == []
    assert store.events()[-1].type is EventType.POLICY_DENIED


async def test_remote_call_with_real_identifiers_is_blocked(store: Store, mandate: Mandate) -> None:
    brain, _, remote = make_brain(store, mandate, identifiers=SensitiveTermIndex(["order_items"]))
    with pytest.raises(EgressBlocked):
        await brain.complete(request(Tier.FRONTIER, text="optimize the order_items query"))
    assert remote.requests == []
    (attempt,) = store.list("egress", EgressAttempt)
    assert attempt.status == "blocked"
    assert attempt.payload.startswith("sha256:")


async def test_allowed_remote_call_records_the_exact_payload(store: Store, mandate: Mandate) -> None:
    brain, _, remote = make_brain(store, mandate)
    remote.script("test.decide", "ok")
    await brain.complete(request(Tier.FRONTIER, text="group child_rows by parent_id"))
    (attempt,) = store.list("egress", EgressAttempt)
    assert attempt.status == "allowed_sent"
    assert "child_rows" in attempt.payload
    run = store.list("model_runs", ModelRun)[0]
    assert run.egress_attempt_id == attempt.id
    assert run.cost.usd_remote > 0


async def test_remote_spend_cap(store: Store, mandate: Mandate) -> None:
    mandate.business_constraints.maximum_monthly_spend_usd = 0.0
    brain, _, remote = make_brain(store, mandate)
    with pytest.raises(SpendLimitReached):
        await brain.complete(request(Tier.FRONTIER, text="hello"))
    assert remote.requests == []


async def test_kill_switch_stops_calls(store: Store, mandate: Mandate, tmp_path: Any) -> None:
    switch = KillSwitch(tmp_path)
    switch.engage("test")
    brain, local, _ = make_brain(store, mandate, killswitch=switch)
    with pytest.raises(KillSwitchEngaged):
        await brain.complete(request())
    assert local.requests == []
