"""The chat creates and modifies widgets through typed tools, by rules and through Brain.complete."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.web.conftest import Client, make_server
from unbidden.brain.providers.mock import MockProvider
from unbidden.brain.router import Brain
from unbidden.config import load_config
from unbidden.contracts.llm import LLMResponse, ToolCall, Usage
from unbidden.store import Store
from unbidden.web.sources import Source

pytestmark = pytest.mark.unit


def _finding_widget(opp: str, **extra: Any) -> dict[str, Any]:
    return {
        "type": "finding",
        "title": "Hallazgo",
        "entity": {"kind": "opportunity", "id": opp},
        "position": {"x": 0, "y": 0},
        "size": {"w": 400, "h": 200},
        **extra,
    }


def _turn(client: Client, text: str, selected: list[str] | None = None) -> tuple[dict[str, Any], list[Any]]:
    events = client.sse("/chat", {"content": text, "selected": selected or [], "planner": "rule"})
    assistant = [e for e in events if e[0] == "message" and e[2]["role"] == "assistant"][-1][2]
    return assistant, events


def test_latency_before_and_after_from_the_selected_finding(client: Client) -> None:
    v = client.put("/presentation", {"base_version": 0, "widgets": [_finding_widget("opp_demo000000000001")]}).json()
    fid = v["widgets"][0]["id"]
    reply, events = _turn(client, "Muéstrame la latencia antes y después de este experimento", [fid])
    assert reply["state"] == "done" and reply["planner"] == "rule"
    assert [c["name"] for c in reply["tool_calls"]] == ["create_widget"] and reply["results"][0]["ok"]
    assert [e[0] for e in events][:3] == ["message", "state", "state"] and events[-1][0] == "done"
    layout = client.get("/presentation").json()
    chart = next(w for w in layout["widgets"] if w["type"] == "chart")
    assert chart["dataRef"]["dataset"] == "experiment.samples"
    assert chart["dataRef"]["params"]["experiment_id"] == "exp_demo000000000001"
    assert (
        chart["view"]["kind"] == "distribution" and chart["view"]["series"] == "arm" and chart["view"]["unit"] == "ms"
    )
    assert chart["provenance"]["freshness"] == "demo" and chart["created_by"] == "chat"
    assert chart["position"]["x"] >= 400 + 48  # placed beside the selected card, not on top of it
    reply, _ = _turn(client, "Cambia ese gráfico a barras", [chart["id"]])
    assert reply["results"][0]["ok"]
    assert (
        next(w for w in client.get("/presentation").json()["widgets"] if w["id"] == chart["id"])["view"]["kind"]
        == "bar"
    )


def test_a_table_of_failed_tests_spend_by_run_and_undo(client: Client) -> None:
    reply, _ = _turn(client, "Añade una tabla con los tests que fallaron")
    assert reply["results"][0]["ok"]
    table = client.get("/presentation").json()["widgets"][-1]
    assert table["type"] == "table" and table["dataRef"]["dataset"] == "tests.failed"
    data = client.post("/data", table["dataRef"]).json()
    assert {r["test"] for r in data["rows"]} == {"tests/test_cart.py::test_remove_expired"}
    reply, _ = _turn(client, "Grafica el gasto por corrida")
    chart = client.get("/presentation").json()["widgets"][-1]
    assert chart["view"] == chart["view"] | {"kind": "bar", "x": "run", "y": "sum_usd"}
    assert chart["dataRef"]["transform"]["group_by"] == "run"
    reply, _ = _turn(client, "Deshaz la última tarjeta")
    assert reply["results"][0]["ok"] and "deshecho" in reply["content"]
    assert [w["type"] for w in client.get("/presentation").json()["widgets"]] == ["table"]


def test_explain_a_block_and_add_its_dependencies_to_the_map(client: Client) -> None:
    v = client.put(
        "/presentation",
        {
            "base_version": 0,
            "widgets": [{"type": "need", "title": "Bloqueo", "entity": {"kind": "block", "id": "blk_demo0000000001"}}],
        },
    ).json()
    reply, _ = _turn(client, "Explícame este bloqueo y añade sus dependencias al mapa", [v["widgets"][0]["id"]])
    assert [c["name"] for c in reply["tool_calls"]] == ["explain", "create_widget", "connect_widgets"]
    assert all(r["ok"] for r in reply["results"])
    assert "deb.debian.org" in reply["content"] and "desbloquea" in reply["content"]
    layout = client.get("/presentation").json()
    assert layout["widgets"][-1]["type"] == "system_map"
    assert layout["edges"][0]["kind"] == "trace" and layout["edges"][0]["note"]


def test_compare_two_runs_needs_two_compatible_selected_experiments(client: Client) -> None:
    reply, _ = _turn(client, "Compara estas dos ejecuciones")
    assert reply["tool_calls"] == [] and "dos ejecuciones" in reply["content"]
    v = client.put(
        "/presentation",
        {
            "base_version": 0,
            "widgets": [_finding_widget("opp_demo000000000001"), _finding_widget("opp_demo000000000002")],
        },
    ).json()
    ids = [w["id"] for w in v["widgets"]]
    reply, _ = _turn(client, "Compara estas dos ejecuciones", ids)
    # Different workloads: the dataset refuses to compare them, and the chart says so instead of showing bars.
    assert reply["results"][0]["ok"] and "not compatible" in reply["content"]
    chart = client.get("/presentation").json()["widgets"][-1]
    assert chart["status"] == "empty" and chart["dataRef"]["dataset"] == "experiment.compare"


def test_when_the_data_is_missing_the_chat_says_so_and_fabricates_nothing(tmp_path: Path) -> None:
    empty = Source(id="live:empty", name="empty", mode="live", store=Store(None), streams=False)
    srv = make_server([empty], tmp_path)
    try:
        c = Client(srv, empty.id)
        reply, _ = _turn(c, "Muéstrame la latencia antes y después")
        assert reply["tool_calls"] == [] and "nada que graficar" in reply["content"]
        assert c.get("/presentation").json()["widgets"] == []
        reply, _ = _turn(c, "Grafica el gasto por corrida")
        assert reply["results"][0]["ok"]  # the widget exists, empty, and says what would fill it
        w = c.get("/presentation").json()["widgets"][-1]
        assert w["status"] == "empty" and "no remote call" in reply["content"]
    finally:
        srv.stop()


def test_invalid_tool_arguments_are_refused_before_anything_is_applied(client: Client) -> None:
    from unbidden.web.chat import ToolRuntime

    src = client  # noqa: F841 - the runtime is exercised directly below
    from unbidden.web.presentation import PresentationStore
    from unbidden.web.sources import demo

    rt = ToolRuntime(demo(), PresentationStore(None), [])
    bad = rt.call("create_widget", {"type": "chart", "title": "x"})
    assert not bad.ok and bad.error is not None and bad.error.code == "invalid"
    bad = rt.call(
        "create_widget",
        {
            "type": "chart",
            "title": "x",
            "dataRef": {"dataset": "experiment.samples"},
            "view": {"kind": "line", "x": "nope"},
        },
    )
    assert not bad.ok and "not a column" in bad.error.detail  # type: ignore[union-attr]
    bad = rt.call(
        "create_widget",
        {"type": "chart", "title": "x", "dataRef": {"dataset": "experiment.samples"}, "script": "alert(1)"},
    )
    assert not bad.ok and bad.error.code == "invalid"  # type: ignore[union-attr]
    assert rt.call("run_experiment", {}).error.code == "unsupported"  # type: ignore[union-attr]
    assert rt.layout().widgets == []


def test_the_brain_planner_goes_through_brain_complete_with_the_tools(tmp_path: Path, mandate: Any) -> None:
    from unbidden.web.sources import demo

    src = demo()
    src.streams = False
    mock = MockProvider()
    mock.script(
        "web.chat",
        LLMResponse(
            tool_calls=[
                ToolCall(
                    id="c1",
                    name="create_widget",
                    arguments={
                        "type": "table",
                        "title": "Oportunidades",
                        "dataRef": {"dataset": "opportunities"},
                        "view": {"kind": "table", "columns": ["title", "level"]},
                    },
                )
            ],
            done_reason="stop",
            usage=Usage(prompt_tokens=10, completion_tokens=10),
        ),
    )
    mock.script("web.chat", "Añadí la tabla de oportunidades.")
    config = load_config(None)
    config.routing["local"].provider = "mock"  # type: ignore[index]
    config.routing["local"].model = "mock-model"  # type: ignore[index]
    brain = Brain(config, {"mock": mock}, Store(None), mandate)  # type: ignore[dict-item]
    srv = make_server([src], tmp_path, brain_for=lambda _s: brain)
    try:
        c = Client(srv, src.id)
        events = c.sse("/chat", {"content": "añade una tabla de oportunidades", "selected": [], "planner": "brain"})
        reply = [e for e in events if e[0] == "message" and e[2]["role"] == "assistant"][-1][2]
        assert reply["planner"] == "brain" and reply["model"] == "mock-model"
        assert reply["content"] == "Añadí la tabla de oportunidades." and reply["results"][0]["ok"]
        assert [e[0] for e in events if e[0] in ("tool_call", "tool_result")] == ["tool_call", "tool_result"]
        assert c.get("/presentation").json()["widgets"][0]["type"] == "table"
        sent = mock.requests[0]
        assert sent.purpose == "web.chat" and {t.name for t in sent.tools} >= {"create_widget", "inspect_data"}
        assert sent.tier.value == "local"
        assert c.get("/chat").json()["messages"][-1]["planner"] == "brain"
        assert c.delete("/chat").json()["deleted"] == 2
    finally:
        srv.stop()


def test_cancel_reports_what_it_could_cancel(client: Client) -> None:
    assert client.post("/chat/cancel").json()["cancelled"] is False


def test_inspect_data_takes_flat_arguments_and_a_full_reference(tmp_path: Path) -> None:
    from unbidden.web.chat import ToolRuntime, tool_specs
    from unbidden.web.presentation import PresentationStore
    from unbidden.web.sources import demo

    src = demo()
    rt = ToolRuntime(src, PresentationStore(tmp_path / "p.db"), [])
    flat = rt.call("inspect_data", {"dataset": "opportunities", "limit": 3})
    assert flat.ok and flat.data is not None and len(flat.data["sample"]) <= 3
    full = rt.call("inspect_data", {"dataset": "opportunities", "transform": {"limit": 3}})
    assert full.ok and full.data is not None and full.data["columns"] == flat.data["columns"]
    bad = rt.call("inspect_data", {"dataset": "opportunities", "params": {"x": {"limit": 500}}})
    assert not bad.ok and bad.error is not None and bad.error.code == "invalid"
    schema = next(t for t in tool_specs() if t.name == "inspect_data").parameters
    assert schema["required"] == ["dataset"] and "transform" not in schema["properties"]


def test_when_the_model_never_calls_a_tool_correctly_the_rules_answer_and_say_so(tmp_path: Path, mandate: Any) -> None:
    from unbidden.web.sources import demo

    src = demo()
    src.streams = False
    mock = MockProvider()
    wrong = LLMResponse(
        tool_calls=[ToolCall(id="c1", name="inspect_data", arguments={"params": {"transform": {"limit": 500}}})],
        done_reason="stop",
        usage=Usage(prompt_tokens=10, completion_tokens=10),
    )
    mock.script("web.chat", wrong, repeat=True)
    config = load_config(None)
    config.routing["local"].provider = "mock"  # type: ignore[index]
    config.routing["local"].model = "mock-model"  # type: ignore[index]
    brain = Brain(config, {"mock": mock}, Store(None), mandate)  # type: ignore[dict-item]
    srv = make_server([src], tmp_path, brain_for=lambda _s: brain)
    try:
        c = Client(srv, src.id)
        events = c.sse(
            "/chat", {"content": "añade una tabla con los tests que fallaron", "selected": [], "planner": "brain"}
        )
        reply = [e for e in events if e[0] == "message" and e[2]["role"] == "assistant"][-1][2]
        assert reply["state"] == "done" and reply["planner"] == "rule"
        assert "Respondí por reglas" in reply["content"] and "inspect_data" in reply["content"]
        assert reply["results"] and reply["results"][0]["ok"]
        assert c.get("/presentation").json()["widgets"][0]["type"] == "table"
        assert len(mock.requests) >= 2  # the engine asked the model to repair before giving up
    finally:
        srv.stop()
