"""The read API, its guards, the datasets and the presentation store, on the demo source."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from tests.web.conftest import TOKEN, Client, make_server
from unbidden.web.server import WebServer
from unbidden.web.sources import Source

pytestmark = pytest.mark.unit


def test_the_api_needs_the_session_token_and_the_right_host(server: WebServer, client: Client) -> None:
    base = client.base
    assert httpx.get(f"{base}/api/session").status_code == 401
    assert httpx.get(f"{base}/api/session", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert (
        httpx.get(
            f"{base}/api/session", headers={"Authorization": f"Bearer {TOKEN}", "Host": "evil.example"}
        ).status_code
        == 403
    )
    assert (
        httpx.get(
            f"{base}/api/session", headers={"Authorization": f"Bearer {TOKEN}", "Origin": "http://evil.example"}
        ).status_code
        == 403
    )
    ok = client.get("/api/session")
    assert ok.status_code == 200 and ok.json()["sources"][0]["mode"] == "demo"
    # The page itself needs no token (the token is in its URL), and never a stack trace.
    assert httpx.get(f"{base}/").status_code == 200


def test_the_summary_states_mode_route_autonomy_and_capabilities(client: Client) -> None:
    s = client.get("/summary").json()
    assert s["workspace"]["mode"] == "demo" and s["freshness"] == "demo"
    assert s["connection"]["route"]["server"] == "local"
    assert s["connection"]["route"]["local"]["provider"] == "ollama"
    assert s["connection"]["autonomy"]["level"] == "supervised"
    assert {"experiments", "world", "connections", "probes", "checks", "proposals", "needs"} <= set(s["capabilities"])
    assert s["activity"]["discovered"]["total"] == 6
    assert s["counts"]["events"] > 40


def test_opportunities_are_paged_and_detailed_with_their_events(client: Client) -> None:
    page = client.get("/opportunities", params={"limit": 2}).json()
    assert page["total"] == 6 and len(page["items"]) == 2 and page["items"][0]["evidence_level"] == 4
    assert page["provenance"]["freshness"] == "demo"
    one = client.get(f"/opportunities/{page['items'][0]['id']}").json()
    assert one["experiment"]["counts"]["sessions"] == 8
    assert any(e["type"] == "verdict.recorded" for e in one["events"])
    assert one["proposal"]["status"] == "ready"
    assert client.get("/opportunities/opp_none").status_code == 404


def test_datasets_resolve_with_bounded_transforms_and_refuse_the_rest(client: Client) -> None:
    cat = client.get("/api/datasets").json()["datasets"]
    assert any(d["id"] == "experiment.samples" for d in cat)
    r = client.post(
        "/data",
        {
            "dataset": "experiment.samples",
            "params": {"experiment_id": "exp_demo000000000001"},
            "transform": {"limit": 50},
        },
    ).json()
    assert len(r["rows"]) == 50 and r["truncated"] and r["provenance"]["completeness"] == "partial"
    assert {c["name"] for c in r["columns"]} == {"arm", "i", "ms", "session", "phase"}
    grouped = client.post(
        "/data",
        {
            "dataset": "experiment.samples",
            "params": {"experiment_id": "exp_demo000000000001"},
            "transform": {"group_by": "arm", "aggregate": {"field": "ms", "fn": "median"}},
        },
    ).json()
    medians = {row["arm"]: row["median_ms"] for row in grouped["rows"]}
    assert medians["before"] > medians["after"] * 1.3
    assert client.post("/data", {"dataset": "sql.raw"}).status_code == 422
    assert (
        client.post(
            "/data",
            {"dataset": "experiment.samples", "transform": {"filter": [{"field": "nope", "op": "eq", "value": 1}]}},
        ).status_code
        == 422
    )
    assert client.post("/data", {"dataset": "experiment.samples", "params": {"evil": "x"}}).status_code == 422
    assert client.post("/data", {"dataset": "events", "transform": {"limit": 99999}}).status_code == 422
    missing = client.post("/data", {"dataset": "experiment.samples", "params": {"experiment_id": "exp_none"}}).json()
    assert (
        missing["rows"] == []
        and missing["provenance"]["completeness"] == "missing"
        and "no experiment" in missing["provenance"]["note"]
    )
    spend = client.post(
        "/data",
        {"dataset": "spend.calls", "transform": {"group_by": "run", "aggregate": {"field": "usd", "fn": "sum"}}},
    ).json()
    assert {row["run"] for row in spend["rows"]} == {"demo-run-1", "demo-run-2"}


def test_the_presentation_is_versioned_validated_and_undoable(client: Client) -> None:
    empty = client.get("/presentation").json()
    assert empty["version"] == 0 and empty["widgets"] == []
    widget = {
        "type": "chart",
        "title": "Latencia",
        "position": {"x": 10, "y": 20},
        "size": {"w": 400, "h": 300},
        "dataRef": {"dataset": "experiment.samples", "params": {"experiment_id": "exp_demo000000000001"}},
        "view": {"kind": "distribution", "x": "ms", "series": "arm"},
    }
    v1 = client.put("/presentation", {"base_version": 0, "widgets": [widget], "reason": "add chart"}).json()
    assert v1["version"] == 1 and v1["widgets"][0]["id"].startswith("w_")
    stale = client.put("/presentation", {"base_version": 0, "widgets": []})
    assert stale.status_code == 409
    bad = client.put("/presentation", {"base_version": 1, "widgets": [{"type": "script", "title": "x"}]})
    assert bad.status_code == 422 and "type" in bad.json()["error"]
    too_big = client.put("/presentation", {"base_version": 1, "widgets": [{**widget, "size": {"w": 99999, "h": 10}}]})
    assert too_big.status_code == 422
    v2 = client.put("/presentation", {"base_version": 1, "widgets": [], "reason": "remove"}).json()
    assert v2["version"] == 2 and v2["history"]["can_undo"]
    undone = client.post("/presentation/undo").json()
    assert undone["version"] == 1 and len(undone["widgets"]) == 1 and undone["history"]["can_redo"]
    redone = client.post("/presentation/redo").json()
    assert redone["version"] == 2 and redone["widgets"] == []
    client.post("/presentation/undo")
    v3 = client.put("/presentation", {"base_version": 1, "widgets": [widget, widget | {"title": "Otra"}]}).json()
    assert v3["version"] == 2 and client.post("/presentation/redo").status_code == 409  # the redo branch is gone


def test_collections_timeline_events_and_world_are_served_paged(client: Client) -> None:
    needs = client.get("/collection/needs").json()
    assert needs["total"] == 1 and needs["items"][0]["status"] == "awaiting_approval"
    assert client.get("/collection/secrets").status_code == 404
    events = client.get("/events", params={"after": 0, "limit": 10}).json()
    assert len(events["items"]) == 10 and events["items"][0]["seq"] == 1 and events["last_seq"] > 10
    world = client.get("/world").json()["world"]
    assert len(world["resources"]) == 12 and all(r["evidence"] for r in world["relations"])
    assert client.get("/timeline").json()["total"] == 0


def test_the_stream_replays_from_a_cursor_and_closes_on_a_source_that_does_not_stream(client: Client) -> None:
    got = client.sse("/events/stream", method="GET", headers={"Last-Event-ID": "40"})
    assert got[0][0] == "hello"
    engine = [g for g in got if g[0] == "engine"]
    assert engine and engine[0][2]["seq"] == 41 and all(g[1] == str(g[2]["seq"]) for g in engine)
    assert got[-1][0] == "closed"


def test_two_sources_are_isolated_in_presentation_and_data(tmp_path: Path, demo_source: Source) -> None:
    other = Source(id="live:other", name="other", mode="live", store=demo_source.store, streams=False)
    srv = make_server([demo_source, other], tmp_path)
    try:
        a, b = Client(srv, demo_source.id), Client(srv, other.id)
        a.put("/presentation", {"base_version": 0, "widgets": [{"type": "note", "title": "solo en demo"}]})
        assert b.get("/presentation").json()["widgets"] == []
        assert b.get("/summary").json()["freshness"] == "current"
        assert a.get("/summary").json()["freshness"] == "demo"
        assert Client(srv, "live:none").get("/summary").status_code == 404
    finally:
        srv.stop()


def test_malicious_text_is_stored_as_data_and_returned_escaped_nowhere_as_html(client: Client) -> None:
    title = "<img src=x onerror=alert(1)> {{7*7}} ${x}"
    v = client.put(
        "/presentation",
        {
            "base_version": 0,
            "widgets": [{"type": "note", "title": title, "content": {"text": "<script>bad()</script>"}}],
        },
    )
    assert v.status_code == 200
    body = client.get("/presentation")
    assert body.headers["content-type"].startswith("application/json")
    assert body.json()["widgets"][0]["title"] == title  # data in, data out; the browser renders it as text
    assert "frame-ancestors 'none'" in body.headers["content-security-policy"]
