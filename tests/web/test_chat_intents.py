"""Inform, analyze, act: deterministic queries need no model; an analysis is one routed call over a digest that
passes the router's gate (classification, policy, the machine ledger) and is refused with the router's reason;
an action is never done from the chat; a chart never starts an experiment."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_router import make_brain
from tests.web.conftest import Client, make_server
from unbidden.brain.spend import SpendLedger
from unbidden.chat.digest import evidence_digest
from unbidden.chat.intent import action_asked, classify_intent
from unbidden.contracts.guardian import Mandate
from unbidden.web.sources import Source, demo

pytestmark = pytest.mark.unit


def _src() -> Source:
    src = demo()
    src.streams = False
    return src


def _turn(c: Client, text: str, planner: str = "auto", selected: list[str] | None = None) -> dict[str, Any]:
    events = c.sse("/chat", {"content": text, "selected": selected or [], "planner": planner})
    return [e for e in events if e[0] == "message" and e[2]["role"] == "assistant"][-1][2]


@pytest.mark.parametrize(
    ("text", "intent", "action"),
    [
        ("Grafica el gasto por corrida", "inform", None),
        ("Show me the failed tests in a table", "inform", None),
        ("Compara estas dos ejecuciones", "inform", None),
        ("Explícame este bloqueo", "inform", None),
        ("¿Por qué fue más lenta la segunda corrida?", "analyze", None),
        ("Resume lo que encontró y qué riesgo tiene", "analyze", None),
        ("Should we prioritise the L4 finding?", "analyze", None),
        ("Aprueba la propuesta opp_demo000000000001", "act", "approve"),
        ("Rechaza esta oportunidad", "act", "reject"),
        ("Deploy the fix now", "act", "deploy"),
        ("Haz rollback del último despliegue", "act", "rollback"),
        ("Para el agente", "act", "kill"),
        ("Resume the agent", "act", "resume"),
        ("Lanza un experimento sobre esto", "act", "experiment"),
        ("Run the scan again", "act", "experiment"),
        ("Deshaz la última tarjeta", "inform", None),  # undo on the canvas is not a rollback
    ],
)
def test_intents_in_spanish_and_english(text: str, intent: str, action: str | None) -> None:
    assert classify_intent(text) == intent
    assert action_asked(text) == action


def test_an_action_is_refused_and_pointed_at_the_panel_or_the_cli_nothing_queued(tmp_path: Path) -> None:
    src = _src()
    srv = make_server([src], tmp_path)
    try:
        c = Client(srv, src.id)
        jobs_before = src.job_counts()
        reply = _turn(c, "Aprueba la propuesta opp_demo000000000001")
        assert reply["route"]["intent"] == "act" and reply["route"]["action"] == "approve"
        assert (
            reply["results"][0]["error"]["code"] == "refused"
            and "unbidden approve" in reply["results"][0]["error"]["need"]
        )
        assert "No lo hago desde el chat" in reply["content"] and reply["tool_calls"] == []
        assert src.job_counts() == jobs_before
        reply = _turn(c, "Lanza un experimento sobre esto")
        assert reply["route"]["action"] == "experiment" and "unbidden try" in reply["content"]
        assert src.job_counts() == jobs_before
    finally:
        srv.stop()


def test_a_chart_is_informing_without_a_model_and_starts_nothing(tmp_path: Path) -> None:
    src = _src()
    srv = make_server([src], tmp_path)
    try:
        c = Client(srv, src.id)
        before = (src.job_counts(), src.count("experiments"))
        reply = _turn(c, "Grafica el gasto por corrida")
        assert reply["route"]["intent"] == "inform" and reply["planner"] == "rule"
        assert reply["route"]["purpose"] is None and "no model" in reply["route"]["reason"]
        assert reply["results"][0]["ok"] and reply["results"][0]["widget_id"]
        assert (src.job_counts(), src.count("experiments")) == before
    finally:
        srv.stop()


def test_solo_api_informs_by_rules_without_ollama_and_sends_nothing(tmp_path: Path, mandate: Mandate) -> None:
    """Option api: the local model is denied and no remote model is needed to read records or draw a table."""
    mandate.models.profile = "frontier"
    mandate.models.local_inference = mandate.models.local_fallback = "deny"
    src = _src()
    src.mandate = mandate
    from unbidden.store import Store

    brain, local, remote = make_brain(Store(None), mandate)
    srv = make_server([src], tmp_path, brain_for=lambda _s: brain)
    try:
        c = Client(srv, src.id)
        reply = _turn(c, "Añade una tabla con los tests que fallaron", planner="brain")
        assert reply["planner"] == "rule" and reply["results"][0]["ok"]
        assert "denies local inference" in reply["route"]["reason"]
        assert local.requests == [] and remote.requests == []
    finally:
        srv.stop()


def test_an_analysis_is_one_routed_call_over_a_record_digest_counted_in_the_ledger(
    tmp_path: Path, mandate: Mandate, spend_home: Path
) -> None:
    from unbidden.store import Store

    src = _src()
    src.mandate = mandate  # local-first, private code stays behind the bridge
    brain, local, remote = make_brain(Store(None), mandate)
    brain.repo_public = True  # GitHub confirmed public: the digest (about the code) may leave
    remote.script("chat.analyze", "Análisis: 6 oportunidades, 1 probada (opp_demo000000000001); sin más datos.")
    srv = make_server([src], tmp_path, brain_for=lambda _s: brain)
    try:
        c = Client(srv, src.id)
        reply = _turn(c, "¿Por qué sólo una oportunidad llegó a probarse?", planner="brain")
        assert reply["planner"] == "brain" and reply["route"]["purpose"] == "chat.analyze"
        assert reply["route"]["tier"] == "code" and reply["route"]["blocked"] is None
        assert reply["content"].startswith("Análisis:") and reply["model"]
        sent = remote.requests[0]
        assert sent.purpose == "chat.analyze" and sent.tools == []
        sources = [m.source for m in sent.messages]
        assert "record" in sources and "runtime" not in sources, "raw records never travel; the digest does"
        digest = next(m.content for m in sent.messages if m.source == "record")
        assert "counts:" in digest and len(digest.encode()) <= 12_100
        assert local.requests == []
        ledger = SpendLedger()
        assert ledger.workspace_month_spend(mandate.workspace) > 0, "the call is in the machine ledger"
        assert brain.store.list("model_runs", type(brain.served_by["chat.analyze"]))[0].purpose == "chat.analyze"
    finally:
        srv.stop()


def test_solo_api_without_a_key_refuses_the_analysis_with_the_routers_reason_never_by_rules(
    tmp_path: Path, mandate: Mandate
) -> None:
    from unbidden.store import Store

    mandate.models.profile = "frontier"
    mandate.models.local_inference = mandate.models.local_fallback = "deny"
    src = _src()
    src.mandate = mandate
    brain, local, remote = make_brain(Store(None), mandate)
    remote.has_key = lambda: False  # type: ignore[attr-defined]
    srv = make_server([src], tmp_path, brain_for=lambda _s: brain)
    try:
        c = Client(srv, src.id)
        reply = _turn(c, "¿Deberíamos priorizar el hallazgo L4?", planner="brain")
        assert reply["planner"] == "rule" and reply["route"]["intent"] == "analyze"
        assert reply["route"]["blocked"] and "denies local inference" in reply["route"]["blocked"]
        assert "unbidden key set" in reply["route"]["hint"]
        assert reply["content"].startswith("No puedo analizar esto con un modelo")
        assert local.requests == [] and remote.requests == []
    finally:
        srv.stop()


def test_the_analysis_respects_the_kill_switch_and_says_how_to_release_it(tmp_path: Path, mandate: Mandate) -> None:
    from unbidden.guardian.killswitch import KillSwitch
    from unbidden.store import Store

    switch = KillSwitch(tmp_path / "ws")
    switch.engage("test")
    src = _src()
    src.mandate = mandate
    brain, _, _ = make_brain(Store(None), mandate, killswitch=switch)
    brain.repo_public = True
    srv = make_server([src], tmp_path, brain_for=lambda _s: brain)
    try:
        c = Client(srv, src.id)
        reply = _turn(c, "¿Por qué está bloqueado?", planner="brain")
        assert "kill switch" in reply["route"]["blocked"] and "unbidden resume" in reply["route"]["hint"]
    finally:
        srv.stop()


def test_the_digest_is_bounded_and_carries_no_emails_ips_or_log_lines() -> None:
    summary = {
        "workspace": {"name": "shop", "mode": "live", "head": "abc", "notes": ["written by ops@corp.example.io"]},
        "counts": {"opportunities": 3},
        "jobs": {"queued": 1},
        "activity": {"discovered": {"total": 3}, "huge": "x" * 50_000},
        "highlights": [{"title": "slow /orders from 10.1.2.3", "status": "open"}],
        "observed_at": "now",
        "freshness": "live",
    }
    results = [{"tool": "inspect_data", "summary": "2024-01-01 ERROR boom\nERROR again\nERROR more"}]
    text = evidence_digest(summary, [{"opportunity": "opp_1", "title": "t"}], results)
    assert len(text.encode()) <= 12_000 and "ops@corp" not in text and "10.1.2.3" not in text
    assert "huge" not in text and "opp_1" in text


def test_a_status_question_is_answered_from_the_record_without_a_model(tmp_path: Path, mandate: Mandate) -> None:
    """Option api with no local model: what happened so far is read from the record by rules, deterministically."""
    mandate.models.profile = "frontier"
    mandate.models.local_inference = mandate.models.local_fallback = "deny"
    src = _src()
    src.mandate = mandate
    srv = make_server([src], tmp_path)
    try:
        c = Client(srv, src.id)
        reply = _turn(c, "¿Qué ha hecho el agente hasta ahora y cuántas oportunidades hay?")
        assert reply["route"]["intent"] == "inform" and reply["planner"] == "rule"
        assert "oportunidades" in reply["content"] and "eventos" in reply["content"]
        assert reply["tool_calls"] == [] and "No he entendido" not in reply["content"]
        reply = _turn(c, "How many experiments are there so far?")
        assert "experimentos" in reply["content"]
    finally:
        srv.stop()
