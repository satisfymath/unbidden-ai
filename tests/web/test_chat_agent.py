"""The chat's agent: a greeting is answered without a model; a free question no rule knows goes to a remote model
with read-only tools under option api, and the gate's refusal is the answer with its hint; the tools read records,
the map, the repository and the docs, and label what they return."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_router import make_brain
from tests.web.conftest import Client, make_server
from unbidden.chat import agent
from unbidden.chat.intent import action_asked, classify_intent
from unbidden.contracts.guardian import Mandate
from unbidden.contracts.llm import ToolCall
from unbidden.web.sources import Source, demo

pytestmark = pytest.mark.unit


def _src() -> Source:
    src = demo()
    src.streams = False
    return src


def _api(mandate: Mandate) -> Mandate:
    mandate.models.profile = "frontier"
    mandate.models.local_inference = mandate.models.local_fallback = "deny"
    return mandate


def _turn(c: Client, text: str) -> dict[str, Any]:
    events = c.sse("/chat", {"content": text, "selected": [], "planner": "auto"})
    return [e for e in events if e[0] == "message" and e[2]["role"] == "assistant"][-1][2]


def test_a_greeting_is_answered_as_a_colleague_without_any_model_call(tmp_path: Path, mandate: Mandate) -> None:
    from unbidden.store import Store

    src = _src()
    src.mandate = _api(mandate)
    brain, local, remote = make_brain(Store(None), mandate)
    srv = make_server([src], tmp_path, brain_for=lambda _s: brain)
    try:
        c = Client(srv, src.id)
        for text in ("hola", "Hola!", "hello unbidden", "buenas tardes"):
            reply = _turn(c, text)
            assert reply["planner"] == "rule" and reply["content"].startswith(
                ("Hola. Soy Unbidden", "Hi. I am Unbidden")
            )
            assert "a greeting" in reply["route"]["reason"]
        assert local.requests == [] and remote.requests == []
    finally:
        srv.stop()


def test_a_free_question_under_api_goes_to_the_remote_model_with_read_only_tools(
    tmp_path: Path, mandate: Mandate, spend_home: Path
) -> None:
    from unbidden.store import Store

    src = _src()
    src.mandate = _api(mandate)
    brain, local, remote = make_brain(Store(None), mandate)
    brain.repo_public = True  # GitHub confirmed public: the records may leave
    remote.script("chat.agent", ToolCall(id="c1", name="records_query", arguments={"topic": "opportunities"}))
    remote.script("chat.agent", ToolCall(id="c2", name="docs", arguments={"topic": "what"}))
    remote.script("chat.agent", "Hoy encontré 6 oportunidades; una llegó a probarse (opp_demo000000000001).")
    srv = make_server([src], tmp_path, brain_for=lambda _s: brain)
    try:
        c = Client(srv, src.id)
        events = c.sse("/chat", {"content": "¿qué hiciste hoy?", "selected": [], "planner": "auto"})
        reply = [e for e in events if e[0] == "message" and e[2]["role"] == "assistant"][-1][2]
        assert reply["planner"] == "brain" and reply["route"]["purpose"] == "chat.agent"
        assert reply["route"]["tier"] == "code" and reply["route"]["blocked"] is None
        assert reply["content"].startswith("Hoy encontré 6 oportunidades")
        assert [r["tool"] for r in reply["results"]] == ["records_query", "docs"] and all(
            r["ok"] for r in reply["results"]
        )
        kinds = [e[0] for e in events]
        assert kinds.index("tool_call") < kinds.index("tool_result") < kinds.index("done")
        first = remote.requests[0]
        assert first.purpose == "chat.agent" and {t.name for t in first.tools} == {
            "records_query", "world_query", "read_file", "grep", "git_log", "docs"
        }  # fmt: skip
        assert first.tool_choice == "auto"
        third = remote.requests[2]
        sources = [m.source for m in third.messages if m.role == "tool"]
        assert sources == ["record", "prompt"], "records are labelled record, the docs prompt; never runtime"
        assert "opp_demo000000000001" in next(m.content for m in third.messages if m.source == "record")
        assert local.requests == []
    finally:
        srv.stop()


def test_without_a_key_the_question_is_refused_with_the_routers_reason_and_a_hint(
    tmp_path: Path, mandate: Mandate
) -> None:
    from unbidden.store import Store

    src = _src()
    src.mandate = _api(mandate)
    brain, local, remote = make_brain(Store(None), mandate)
    brain.repo_public = True
    remote.has_key = lambda: False  # type: ignore[attr-defined]
    srv = make_server([src], tmp_path, brain_for=lambda _s: brain)
    try:
        c = Client(srv, src.id)
        reply = _turn(c, "¿qué hiciste hoy?")
        assert reply["planner"] == "rule" and reply["route"]["purpose"] == "chat.agent"
        assert reply["route"]["blocked"] and reply["route"]["hint"]
        assert reply["content"].startswith("No puedo responder eso con un modelo aquí")
        assert remote.requests == [] and local.requests == []
    finally:
        srv.stop()


def test_a_question_a_rule_knows_still_goes_by_rules_under_api(tmp_path: Path, mandate: Mandate) -> None:
    from unbidden.store import Store

    src = _src()
    src.mandate = _api(mandate)
    brain, _local, remote = make_brain(Store(None), mandate)
    srv = make_server([src], tmp_path, brain_for=lambda _s: brain)
    try:
        c = Client(srv, src.id)
        reply = _turn(c, "Añade una tabla con los tests que fallaron")
        assert reply["planner"] == "rule" and reply["results"][0]["ok"]
        assert remote.requests == []
    finally:
        srv.stop()


def test_the_tools_read_records_the_map_the_repository_and_the_docs_and_label_them(tmp_path: Path) -> None:
    src = _src()
    tools = agent.AgentTools(src)
    result, label = tools.call("records_query", {"topic": "status"})
    assert result.ok and label == "record" and "counts:" in (result.data or {})["text"]
    result, label = tools.call("records_query", {"topic": "opportunities"})
    assert result.ok and "opp_demo000000000001" in (result.data or {})["text"] and "/7 " in (result.data or {})["text"]
    result, label = tools.call("world_query", {"kind": "summary"})
    assert label == "record"
    result, label = tools.call("docs", {"topic": "what"})
    assert result.ok and label == "prompt" and "proactive engineering agent" in (result.data or {})["text"]
    result, _ = tools.call("docs", {"topic": "nothing"})
    assert not result.ok and result.error is not None and result.error.code == "invalid"
    result, _ = tools.call("teleport", {})
    assert not result.ok and result.error is not None and result.error.code == "unsupported"
    import subprocess

    repo = tmp_path / "r"
    repo.mkdir()
    (repo / "app.py").write_text("def slow():\n    return 1\n")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x"],
                   check=True)  # fmt: skip
    src.repo = repo
    result, label = tools.call("read_file", {"path": "app.py", "start_line": 1, "end_line": 5})
    assert result.ok and label == "repo" and (result.data or {})["text"].startswith("1: def slow():")
    result, _ = tools.call("read_file", {"path": "../etc/passwd"})
    assert (result.data or {})["text"] == "paths are relative to the repository"
    result, label = tools.call("grep", {"text": "slow"})
    assert result.ok and "app.py:1:" in (result.data or {})["text"]
    result, _ = tools.call("git_log", {"count": 3})
    assert result.ok and " x" in (result.data or {})["text"]


def test_para_que_sirve_is_a_question_not_a_kill() -> None:
    assert (
        classify_intent("¿para qué sirve todo esto?") == "inform" and action_asked("¿para qué sirve todo esto?") is None
    )
    assert classify_intent("para el agente") == "act" and action_asked("para el agente") == "kill"
    assert action_asked("para al agente ahora") == "kill"
