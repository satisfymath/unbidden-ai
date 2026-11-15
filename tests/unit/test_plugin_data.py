"""Plugins and the web canvas: an installed package offers a workspace's own data as datasets and adds tools to
the chat. Neither can stand in for what is shipped, and one that fails is a result, not a crash.

The fake plugin is a real distribution on `sys.path`, as in `test_plugins.py`."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from unbidden import plugins
from unbidden.store import Store
from unbidden.web import datasets
from unbidden.web.chat import ToolRuntime, tool_specs
from unbidden.web.contracts import DataRef
from unbidden.web.presentation import PresentationStore
from unbidden.web.sources import Source

pytestmark = pytest.mark.unit

MODULE = """
from pydantic import BaseModel

from unbidden.web.contracts import Column, ToolResult
from unbidden.web.datasets import Dataset


def _tonnes(source, params):
    rows = [{"turno": "A", "t": 9452.0}, {"turno": "B", "t": 29800.0}]
    return [Column(name="turno", type="string"), Column(name="t", type="number", unit="t")], rows, None


def _made(id_):
    fields = [Column(name="turno", type="string"), Column(name="t", type="number", unit="t")]
    return Dataset(id_, "Tonnes by shift, from the mine's lake", fields, [], _tonnes)


class Mine:
    name = "mine"

    def datasets(self, source):
        # The second and third try to take ids that are not this provider's.
        return [_made("mine.erp.produccion_turno"), _made("opportunities"), _made("other.table")]


class Events(Mine):  # the first part of shipped ids
    name = "events"


class Failing:
    name = "failing"

    def datasets(self, source):
        raise RuntimeError("the lake is down")


class AskArgs(BaseModel):
    pedido: str


class Ask:
    name = "mine_answer"
    description = "Answer a manager's request from the mine's lake."
    args = AskArgs

    def run(self, source, brain, args):
        if args.pedido == "boom":
            raise RuntimeError("no lake")
        return ToolResult(ok=True, tool="mine_answer", summary=f"{args.pedido}: 0.83", data={"brain": brain})


class Slow(Ask):
    name = "mine_slow"

    async def run(self, source, brain, args):
        return ToolResult(ok=True, tool="mine_slow", summary="later")


class Inspect(Ask):  # tries to take a shipped tool
    name = "inspect_data"
"""

ENTRY_POINTS = """[unbidden.datasets]
mine = fake_data_plugin:Mine
events = fake_data_plugin:Events
failing = fake_data_plugin:Failing

[unbidden.chat_tools]
mine_answer = fake_data_plugin:Ask
mine_slow = fake_data_plugin:Slow
inspect_data = fake_data_plugin:Inspect
"""


@pytest.fixture
def installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    root = tmp_path / "site"
    root.mkdir()
    (root / "fake_data_plugin.py").write_text(MODULE)
    info = root / "fake_data_plugin-0.1.dist-info"
    info.mkdir()
    (info / "METADATA").write_text("Metadata-Version: 2.1\nName: fake-data-plugin\nVersion: 0.1\n")
    (info / "entry_points.txt").write_text(ENTRY_POINTS)
    monkeypatch.syspath_prepend(str(root))
    plugins.reload()
    yield root
    sys.modules.pop("fake_data_plugin", None)
    plugins.reload()


@pytest.fixture
def source() -> Source:
    return Source(id="live:mine", name="mine", mode="live", store=Store(None), streams=False)


def test_a_workspace_offers_its_plugins_datasets_beside_the_shipped_ones(installed: Path, source: Source) -> None:
    ids = [d["id"] for d in datasets.catalogue(source)]
    assert "mine.erp.produccion_turno" in ids and ids.count("opportunities") == 1 and "other.table" not in ids
    assert "mine.erp.produccion_turno" not in [d["id"] for d in datasets.catalogue()]  # no workspace, nothing offered
    assert {b.name for b in plugins.problems()} == {"events", "inspect_data"}


def test_a_plugins_dataset_resolves_with_transforms_and_provenance(installed: Path, source: Source) -> None:
    ref = DataRef.model_validate(
        {"dataset": "mine.erp.produccion_turno", "transform": {"sort": {"field": "t", "dir": "desc"}, "limit": 1}}
    )
    got = datasets.resolve(source, ref)
    assert got.rows == [{"turno": "B", "t": 29800.0}] and got.total == 2 and got.provenance.source == "live:mine"
    with pytest.raises(datasets.DatasetError, match="unknown dataset"):
        datasets.resolve(source, DataRef(dataset="other.table"))


def test_the_chat_can_chart_a_plugins_dataset(installed: Path, source: Source, tmp_path: Path) -> None:
    rt = ToolRuntime(source, PresentationStore(tmp_path / "p.db"), [])
    made = rt.call("create_widget", {"type": "chart", "title": "Toneladas por turno",
                                     "dataRef": {"dataset": "mine.erp.produccion_turno"},
                                     "view": {"kind": "bar", "x": "turno", "y": "t"}})  # fmt: skip
    assert made.ok and made.widget_id


def test_a_plugins_tool_is_offered_validated_and_run(installed: Path, source: Source, tmp_path: Path) -> None:
    names = [t.name for t in tool_specs()]
    assert names.count("inspect_data") == 1 and {"mine_answer", "mine_slow"} <= set(names)
    rt = ToolRuntime(source, PresentationStore(tmp_path / "p.db"), [])
    rt.brain = "the workspace's brain"
    ran = rt.call("mine_answer", {"pedido": "disponibilidad de palas"})
    assert ran.ok and ran.data == {"brain": "the workspace's brain"}
    bad = rt.call("mine_answer", {})
    assert not bad.ok and bad.error is not None and bad.error.code == "invalid"
    failed = rt.call("mine_answer", {"pedido": "boom"})
    assert not failed.ok and failed.error is not None and "no lake" in failed.error.detail
    # A tool that awaits runs in the model's turn, not in a plan made by rules.
    refused = rt.call("mine_slow", {"pedido": "x"})
    assert not refused.ok and refused.error is not None and refused.error.code == "unsupported"
    assert asyncio.run(rt.acall("mine_slow", {"pedido": "x"})).summary == "later"
    assert asyncio.run(rt.acall("inspect_data", {"dataset": "opportunities"})).tool == "inspect_data"
