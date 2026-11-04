from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from unbidden.brain.providers.mock import MockProvider
from unbidden.brain.router import TRANSCRIPT_FIELD_CAP, Brain
from unbidden.brain.spend import SpendLedger
from unbidden.cli import main
from unbidden.config import load_config
from unbidden.contracts.guardian import Mandate
from unbidden.contracts.llm import LLMRequest, Message, ModelRun, Tier, Transcript
from unbidden.export import COLLECTIONS, MANIFEST, ExportRefused, export_bundle
from unbidden.store import Store

pytestmark = pytest.mark.unit

# A fake AWS access key the scanner recognizes; built in two parts so no tool mistakes this file for a leak.
PLANTED = "AKIA" + "Q7XK2M9PLW4RT8VZ"
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"verdict": {"type": "string"}},
    "required": ["verdict"],
}


class RemoteMock(MockProvider):
    host = "api.meta.ai"


def make_brain(store: Store, mandate: Mandate) -> tuple[Brain, MockProvider, RemoteMock]:
    config = load_config()
    config.routing[Tier.LOCAL].provider = "local"
    config.routing[Tier.FRONTIER].provider = "remote"
    config.routing[Tier.CODE].provider = "remote"
    local, remote = MockProvider(), RemoteMock()
    return Brain(config, {"local": local, "remote": remote}, store, mandate), local, remote


def remote_request(text: str = "group child_rows by parent_id") -> LLMRequest:
    return LLMRequest(purpose="bridge.solve", tier=Tier.FRONTIER,
                      messages=[Message(role="user", content=text, source="synthetic")])  # fmt: skip


async def test_a_remote_call_leaves_a_transcript_with_request_and_answer(store: Store, mandate: Mandate) -> None:
    brain, _, remote = make_brain(store, mandate)
    remote.script("bridge.solve", "use a dict of lists")
    await brain.complete(remote_request())
    (run,) = store.list("model_runs", ModelRun)
    (tr,) = store.list("transcripts", Transcript)
    assert tr.model_run_id == run.id and tr.tier is run.tier and tr.tier.remote and tr.ok
    assert [(m.role, m.source, m.content) for m in tr.messages] == [
        ("user", "synthetic", "group child_rows by parent_id")
    ]
    assert tr.answer == "use a dict of lists"
    assert (tr.tokens_in, tr.tokens_out) == (100, 20) and tr.usd == pytest.approx(run.cost.usd)
    assert tr.provider == run.provider and tr.model == run.model and len(tr.payload_sha256) == 64


async def test_local_and_json_calls_leave_a_transcript_of_every_attempt(store: Store, mandate: Mandate) -> None:
    brain, local, _ = make_brain(store, mandate)
    local.script("test.decide", "not json", {"verdict": "fix"})
    request = LLMRequest(purpose="test.decide", tier=Tier.LOCAL, response_schema=SCHEMA,
                         messages=[Message(role="user", content="decide")])  # fmt: skip
    value, _ = await brain.complete_json(request)
    assert value == {"verdict": "fix"}
    first, second = sorted(store.list("transcripts", Transcript), key=lambda t: t.attempt)
    assert first.tier is Tier.LOCAL and not first.ok and first.problem and first.answer == "not json"
    assert second.ok and second.answer_json == {"verdict": "fix"} and second.response_schema == SCHEMA
    assert "rejected" in second.messages[-1].content  # the repair message, as it was sent


async def test_a_failed_call_leaves_a_transcript_without_an_answer(store: Store, mandate: Mandate) -> None:
    brain, _, _ = make_brain(store, mandate)  # nothing scripted: the provider fails
    with pytest.raises(LookupError):
        await brain.complete(LLMRequest(purpose="test.decide", tier=Tier.LOCAL,
                                        messages=[Message(role="user", content="decide")]))  # fmt: skip
    (tr,) = store.list("transcripts", Transcript)
    assert not tr.ok and tr.answer is None and tr.problem and tr.problem.startswith("provider error")


async def test_a_long_field_is_cut_and_said_so(store: Store, mandate: Mandate) -> None:
    brain, local, _ = make_brain(store, mandate)
    local.script("test.decide", "x" * (TRANSCRIPT_FIELD_CAP + 10))
    await brain.complete(LLMRequest(purpose="test.decide", tier=Tier.LOCAL,
                                    messages=[Message(role="user", content="decide")]))  # fmt: skip
    (tr,) = store.list("transcripts", Transcript)
    assert tr.truncated == ["answer"] and tr.answer is not None and "10 more characters cut" in tr.answer


async def test_a_planted_secret_is_redacted_in_the_transcript_and_absent_from_the_export(
    store: Store, mandate: Mandate, tmp_path: Path
) -> None:
    brain, local, _ = make_brain(store, mandate)
    # In the repository's text (masked before the call) and in the model's answer (redacted by the store).
    local.script("test.decide", f"the key is {PLANTED}")
    code = f'AWS_KEY = "{PLANTED}"\nprint(1)\n'
    await brain.complete(LLMRequest(purpose="test.decide", tier=Tier.LOCAL,
                                    messages=[Message(role="user", content=code, source="repo")]))  # fmt: skip
    (tr,) = store.list("transcripts", Transcript)
    assert PLANTED not in tr.messages[0].content and "print(1)" in tr.messages[0].content
    assert tr.answer is not None and PLANTED not in tr.answer and tr.answer.startswith("the key is")
    assert all(PLANTED not in text for text in store.dump_all_text())
    out = tmp_path / "bundle"
    export_bundle(store, mandate, out)
    for path in out.iterdir():
        assert PLANTED not in path.read_text()
    assert len((out / "transcripts.jsonl").read_text().splitlines()) == 1


async def test_the_bundle_has_a_manifest_whose_sha256s_match(store: Store, mandate: Mandate, tmp_path: Path) -> None:
    brain, local, remote = make_brain(store, mandate)
    remote.script("bridge.solve", "ok")
    local.script("test.decide", "ok")
    await brain.complete(remote_request())
    await brain.complete(LLMRequest(purpose="test.decide", tier=Tier.LOCAL,
                                    messages=[Message(role="user", content="decide")]))  # fmt: skip
    other = SpendLedger()
    other.reserve(est_usd=0.01, workspace="another", purpose="x", provider="p", model="m", attempt=1,
                  correlation_id=None)  # fmt: skip
    out = tmp_path / "bundle"
    manifest = export_bundle(store, mandate, out)
    on_disk = json.loads((out / MANIFEST).read_text())
    assert on_disk == manifest and manifest["workspace"] == "shop" and manifest["unbidden_version"]
    names = {f["name"] for f in manifest["files"]}
    assert {f"{c}.jsonl" for c in COLLECTIONS} <= names
    assert {"events.jsonl", "audit.jsonl", "spend.jsonl", "deploy_ledger.jsonl", "mandate.json"} <= names
    assert sorted(p.name for p in out.iterdir()) == sorted([*names, MANIFEST])
    for f in manifest["files"]:
        data = (out / f["name"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == f["sha256"] and len(data) == f["bytes"]
        if f["name"].endswith(".jsonl"):
            assert len(data.decode().splitlines()) == f["lines"]
    lines = {f["name"]: f["lines"] for f in manifest["files"]}
    assert lines["transcripts.jsonl"] == 2 and lines["model_runs.jsonl"] == 2
    spend = [json.loads(line) for line in (out / "spend.jsonl").read_text().splitlines()]
    assert [r["workspace"] for r in spend] == ["shop"]  # only this workspace's rows of the machine's ledger


def test_the_export_refuses_a_secret_the_redaction_missed(
    store: Store, mandate: Mandate, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import unbidden.export
    import unbidden.store.sqlite

    monkeypatch.setattr(unbidden.store.sqlite, "redact_json", lambda value: value)  # pyright: ignore[reportUnknownLambdaType]
    monkeypatch.setattr(unbidden.export, "redact_json", lambda value: value)  # pyright: ignore[reportUnknownLambdaType]
    store.put("asks", ModelRun.model_validate({"purpose": "x", "tier": "local", "provider": "p", "model": "m",
              "attempt": 1, "ok": True, "usage": {}, "cost": {}, "problem": f"leaked {PLANTED}"}))  # fmt: skip
    out = tmp_path / "bundle"
    with pytest.raises(ExportRefused) as refused:
        export_bundle(store, mandate, out)
    assert refused.value.file == "asks.jsonl" and refused.value.rule == "aws_access_key"
    assert PLANTED not in str(refused.value)
    assert not out.exists()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_unbidden_export_writes_under_the_workspace_and_refuses_with_the_rule(
    repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert main(["init"]) == 0
    capsys.readouterr()
    assert main(["export", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    out = Path(data["out"])
    assert out.parent == repo / ".unbidden" / "export" and (out / MANIFEST).exists()
    assert not any(p.suffix in (".db", ".env") or p.name == "ui.json" for p in out.iterdir())

    import unbidden.export

    monkeypatch.setattr(unbidden.export, "find_secret", lambda path: "aws_access_key")  # pyright: ignore[reportUnknownLambdaType]
    target = repo / "elsewhere"
    assert main(["export", "--out", str(target)]) == 1
    assert "aws_access_key" in capsys.readouterr().err and not target.exists()
