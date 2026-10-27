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


def test_a_bare_environment_key_takes_its_value_from_the_tracked_dotenv(tmp_path: Path) -> None:
    compose = """services:
  frontend:
    image: x/frontend
    environment:
      - CART_ADDR
      - UNSET_ADDR
  cart:
    image: x/cart
  cache:
    image: ghcr.io/valkey-io/valkey:9.1.2-alpine3.24
"""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "compose.yaml").write_text(compose)
    (tmp_path / ".env").write_text("CART_PORT=7070\nCART_ADDR=cart:${CART_PORT}\n")
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    world = WorldModel(rev="HEAD")
    discover_static(tmp_path, "HEAD", detect_stack(tmp_path), world)
    assert ("service:frontend", "service:cart", "calls") in {r.key for r in world.relations}
    assert world.resources["service:cache"].attributes["engine"] == "valkey"
    assert any("UNSET_ADDR" in b.what for b in world.blind_spots)


def test_tables_outside_public_or_the_default_database_get_qualified_ids() -> None:
    from unbidden.world.runtime import table_id

    assert table_id("app", "app", "public", "item") == "item"
    assert table_id("app", "app", "catalog", "products") == "catalog.products"
    assert table_id("astronomy_db", "postgres", "catalog", "products") == "astronomy_db/catalog.products"


def test_a_key_that_says_host_makes_a_bare_service_name_an_address() -> None:
    from unbidden.observe.compose import Compose, Service
    from unbidden.world.static import service_references

    def svc(name: str, **env: str) -> Service:
        return Service(name, "img", None, None, env, (), ())

    compose = Compose(
        path="compose.yaml",
        services={
            "proxy": svc("proxy", FLAGD_HOST="flagd", FLAGD_PORT="8013", OTEL_SERVICE_NAME="flagd"),
            "flagd": svc("flagd"),
        },
    )
    assert service_references(compose, compose.services["proxy"]) == [("FLAGD_HOST", "flagd", "flagd")]


def test_several_compose_files_merge_as_compose_does(tmp_path: Path) -> None:
    from unbidden.observe.compose import deployed_compose_files, load_compose

    base = """services:
  cart:
    image: x/cart
    environment:
      - VALKEY_ADDR=valkey:6379
    depends_on: [valkey]
  valkey:
    image: valkey/valkey:9
"""
    extra = """services:
  cart:
    environment:
      OTEL_EXPORTER_OTLP_ENDPOINT: http://collector:4317
    depends_on: [collector]
  collector:
    image: otel/collector
"""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "compose.yaml").write_text(base)
    (tmp_path / "compose.extra.yaml").write_text(extra)
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    files = deployed_compose_files(
        tmp_path, [f"{tmp_path}/compose.yaml,{tmp_path}/compose.extra.yaml,/elsewhere/x.yaml"]
    )
    assert files == ["compose.yaml", "compose.extra.yaml"]
    compose = load_compose(tmp_path, "HEAD", files)
    assert compose is not None and set(compose.services) == {"cart", "valkey", "collector"}
    assert compose.services["cart"].environment == {
        "VALKEY_ADDR": "valkey:6379",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4317",
    }
    assert compose.services["cart"].depends_on == ("valkey", "collector")
    assert compose.path == "compose.yaml+compose.extra.yaml"
    default = load_compose(tmp_path, "HEAD")  # nothing known about the deployment: the default file
    assert default is not None and set(default.services) == {"cart", "valkey"}


def test_traefik_router_labels_become_routes_from_the_proxy(tmp_path: Path) -> None:
    compose = """services:
  proxy:
    image: traefik:3.0
  backend:
    image: x/backend
    labels:
      - traefik.enable=true
      - traefik.http.routers.backend-http.rule=Host(`api.localhost`)
  adminer:
    image: adminer
    labels:
      traefik.http.routers.adminer-http.rule: Host(`adminer.localhost`)
  hidden:
    image: x/hidden
    labels: [traefik.enable=false, traefik.http.routers.h.rule=Host(`h`)]
"""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "compose.yml").write_text(compose)
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    world = WorldModel(rev="HEAD")
    discover_static(tmp_path, "HEAD", detect_stack(tmp_path), world)
    routes = {(r.src, r.dst) for r in world.relations if r.predicate == "calls"}
    assert routes == {("service:proxy", "service:backend"), ("service:proxy", "service:adminer")}


def test_service_directories_with_their_own_manifest_and_lock_are_found(tmp_path: Path) -> None:
    from unbidden.observe.scan import service_dirs

    compose = """services:
  payment:
    build: {context: ./src/payment}
  loadgen:
    build: {context: ., dockerfile: src/load-generator/Dockerfile}
  go-svc:
    build: {context: ./src/checkout}
  db:
    image: postgres:16
"""
    files = {
        "compose.yaml": compose,
        "src/payment/package.json": "{}",
        "src/payment/package-lock.json": "{}",
        "src/load-generator/requirements.txt": "locust==2.0\n",
        "src/load-generator/Dockerfile": "FROM python\n",
        "src/checkout/go.mod": "module x\n",
    }
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for path, text in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    assert service_dirs(tmp_path, "HEAD", detect_stack(tmp_path)) == ["src/load-generator", "src/payment"]


def test_routes_take_their_own_routers_prefix_and_bare_mounts_are_skipped(tmp_path: Path) -> None:
    files = {
        "requirements.txt": "x\n",
        "app/routes/shopping.py": (
            "from fastapi import APIRouter\n"
            'item_router = APIRouter(prefix="/shopping/items", tags=["a"])\n'
            'router = UserAPIRouter(prefix="/shopping/lists")\n'
            '@item_router.get("/{item_id}")\ndef a(): ...\n'
            '@router.post("/{list_id}/items")\ndef b(): ...\n'
            '@router.get("")\ndef c(): ...\n'
        ),
        "app/routes/plain.py": 'from fastapi import APIRouter\nrouter = APIRouter()\n@router.get("")\ndef d(): ...\n',
    }
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for path, text in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    world = WorldModel(rev="HEAD")
    discover_static(tmp_path, "HEAD", detect_stack(tmp_path), world)
    names = {r.name for r in world.resources.values() if r.kind == "endpoint"}
    assert names == {"GET /shopping/items/{item_id}", "POST /shopping/lists/{list_id}/items", "GET /shopping/lists"}


def test_reconciling_ignores_parameter_names_and_ranks_twice_mounted_routes_by_their_file() -> None:
    world = WorldModel(rev="HEAD")
    for route, file in [
        ("GET /cookbooks/{item_id}", "app/routes/explore/public_cookbooks.py"),
        ("GET /households/cookbooks/{item_id}", "app/routes/households/cookbooks.py"),
        ("GET /tags", "app/routes/tags.py"),
    ]:
        world.add(
            Resource(
                id=f"endpoint:{route}",
                kind="endpoint",
                name=route,
                attributes={"file": file, "line": 1},
                status=EpistemicStatus.INFERRED,
                confidence=0.7,
                evidence=[EvidenceRef(kind="file", locator=f"{file}:1")],
            )
        )
    public, private = "/api/explore/groups/{slug}/cookbooks/{id}", "/api/households/cookbooks/{id}"
    tags = ("/api/explore/groups/{slug}/tags", "/api/organizers/tags")
    live = {f"GET {p}" for p in (public, private, *tags)}
    assert _reconcile_endpoint(world, "GET", private, live)["file"] == "app/routes/households/cookbooks.py"
    assert _reconcile_endpoint(world, "GET", public, live)["file"] == "app/routes/explore/public_cookbooks.py"
    assert _reconcile_endpoint(world, "GET", tags[0], live) == {}  # as close to the file as tags[1], but longer
    assert _reconcile_endpoint(world, "GET", tags[1], live)["file"] == "app/routes/tags.py"
