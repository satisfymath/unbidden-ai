from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from unbidden.contracts.common import EpistemicStatus, EvidenceRef
from unbidden.contracts.world import Resource, WorldModel
from unbidden.observe.stack import detect_stack
from unbidden.world.discover import sensitive_terms
from unbidden.world.relations import handler_source
from unbidden.world.runtime import _reconcile_endpoint  # pyright: ignore[reportPrivateUsage]
from unbidden.world.static import discover_static

pytestmark = pytest.mark.unit

MODELS = """from sqlmodel import SQLModel, Field

class ItemBase(SQLModel):
    title: str

class Item(ItemBase, table=True):
    id: int = Field(primary_key=True)

class Order(Base):
    __tablename__ = "orders"
"""
ROUTES = """from fastapi import APIRouter

router = APIRouter(prefix="/items")

@router.get("/")
def read_items():
    return session.exec(select(Item)).all()

@router.post("/")
def create_item():
    session.add(Item())
"""
COMPOSE = """services:
  db:
    image: postgres:18
  api:
    build: {context: ., dockerfile: api/Dockerfile}
    depends_on: [db]
    environment:
      DATABASE_URL: postgresql://u:p@db:5432/app
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    files = {"app/models.py": MODELS, "app/routes/items.py": ROUTES, "compose.yml": COMPOSE, "requirements.txt": "x\n"}
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for path, text in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    return tmp_path


def test_static_discovery_marks_declared_facts_observed_and_code_reads_inferred(repo: Path) -> None:
    world = WorldModel(rev="HEAD")
    discover_static(repo, "HEAD", detect_stack(repo), world)
    assert world.resources["service:db"].kind == "database"
    assert world.resources["service:db"].status is EpistemicStatus.OBSERVED
    assert {r.id for r in world.of_kind("table")} == {"table:item", "table:orders"}
    assert all(t.status is EpistemicStatus.INFERRED for t in world.of_kind("table"))
    assert {e.name for e in world.of_kind("endpoint")} == {"GET /items/", "POST /items/"}
    predicates = {(r.src, r.dst, r.predicate) for r in world.relations}
    assert ("service:api", "service:db", "depends_on") in predicates
    assert ("service:api", "service:db", "uses_database") in predicates


def test_observation_replaces_inference_never_the_reverse() -> None:
    world = WorldModel(rev="r")
    ref = [EvidenceRef(kind="file", locator="x")]
    world.add(
        Resource(
            id="table:item",
            kind="table",
            name="item",
            attributes={"model": "Item"},
            status=EpistemicStatus.INFERRED,
            confidence=0.8,
            evidence=ref,
        )
    )
    world.add(
        Resource(
            id="table:item",
            kind="table",
            name="item",
            attributes={"rows_estimate": 10},
            status=EpistemicStatus.OBSERVED,
            confidence=1.0,
            evidence=ref,
        )
    )
    world.add(
        Resource(
            id="table:item",
            kind="table",
            name="item",
            attributes={"rows_estimate": 99},
            status=EpistemicStatus.INFERRED,
            confidence=0.5,
            evidence=ref,
        )
    )
    table = world.resources["table:item"]
    assert table.status is EpistemicStatus.OBSERVED
    assert table.attributes == {"model": "Item", "rows_estimate": 10}


def test_live_endpoint_takes_over_its_inferred_route(repo: Path) -> None:
    world = WorldModel(rev="HEAD")
    discover_static(repo, "HEAD", detect_stack(repo), world)
    live = {"GET /api/v1/items/", "POST /api/v1/items/"}
    extra = _reconcile_endpoint(world, "GET", "/api/v1/items/", live)
    assert extra == {"file": "app/routes/items.py", "line": 5}
    assert "endpoint:GET /items/" not in world.resources


def test_handler_source_stops_at_the_next_handler(repo: Path) -> None:
    code = handler_source(repo, "HEAD", "app/routes/items.py", 5)
    assert "def read_items" in code and "create_item" not in code


def test_world_names_are_sensitive(repo: Path) -> None:
    world = WorldModel(rev="HEAD")
    discover_static(repo, "HEAD", detect_stack(repo), world)
    index = sensitive_terms(world)
    assert {"orders", "item", "items"} <= index.terms and "db" not in index.terms  # under four characters: ignored


def test_environment_addresses_become_inferred_calls_and_bare_names_do_not(tmp_path: Path) -> None:
    compose = """services:
  cart:
    image: ghcr.io/x/cart
    environment:
      VALKEY_ADDR: valkey-cart:6379
  checkout:
    image: ghcr.io/x/checkout
    environment:
      CART_ADDR: cart:7070
      OTEL_EXPORTER_OTLP_ENDPOINT: http://otel-collector:4317
      SERVICE_NAME: cart
  otel-collector:
    image: otel/collector
  valkey-cart:
    image: redis:7
"""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "compose.yml").write_text(compose)
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    world = WorldModel(rev="HEAD")
    discover_static(tmp_path, "HEAD", detect_stack(tmp_path), world)
    links = {(r.src, r.dst, r.predicate): r for r in world.relations}
    assert ("service:checkout", "service:cart", "calls") in links
    assert ("service:checkout", "service:otel-collector", "calls") in links
    assert ("service:cart", "service:valkey-cart", "uses_database") in links
    assert links[("service:checkout", "service:cart", "calls")].status is EpistemicStatus.INFERRED
    assert links[("service:checkout", "service:cart", "calls")].evidence[0].locator.endswith("environment.CART_ADDR")
    # SERVICE_NAME=cart names the service, it does not address it: only CART_ADDR made the link.
    assert sum(1 for k in links if k[:2] == ("service:checkout", "service:cart")) == 1
