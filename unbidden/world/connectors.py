"""The connectors the World Model is built from, described: what each can learn, what it needs, what it costs.

Every fact a connector produces carries `source=<id>@<version>`, so a later run of the same connector can tell
which of its earlier facts it no longer sees. None of them modifies anything.
"""

from __future__ import annotations

from unbidden.contracts.world import ConnectorSpec

GIT_STATIC = ConnectorSpec(
    id="git-static",
    version=1,
    purpose="what the repository declares about the system, read from git at one revision",
    discovers=["repo", "service", "database", "ci_job", "table (from models)", "endpoint (from route decorators)"],
    capability="repo.read",
    cost="local: git show of tracked files, no execution",
    scope="tracked files of this repository at the revision being mapped",
)
COMPOSE_DOCKER = ConnectorSpec(
    id="compose-docker",
    version=1,
    purpose="which containers of this compose project run, from which images, since when",
    discovers=["container", "image", "deployment"],
    measures=["container state and health"],
    capability="runtime.read",
    cost="local: `docker compose ps` and one `docker inspect` per map",
    scope="containers labelled with this workspace's compose project only; other projects on the host are ignored",
)
OPENAPI_HTTP = ConnectorSpec(
    id="openapi-http",
    version=1,
    purpose="the endpoints a running service describes about itself",
    discovers=["endpoint"],
    capability="runtime.read",
    cost="local: up to five GETs per published port",
    scope="published ports of this project's containers on 127.0.0.1",
)
POSTGRES_READONLY = ConnectorSpec(
    id="postgres-readonly",
    version=1,
    purpose="tables, sizes, indexes and foreign keys of a Postgres the project runs",
    discovers=["table", "index", "foreign key"],
    measures=["row estimates", "table sizes"],
    capability="runtime.read",
    cost="local: three catalog queries in a read-only transaction inside the database's own container",
    scope="schema `public` of postgres services declared in compose; credentials never leave the container",
)
LLM_RELATIONS = ConnectorSpec(
    id="local-model-relations",
    version=1,
    purpose="which tables an endpoint's handler reads or writes, as read by the local model",
    discovers=["reads", "writes"],
    capability="repo.read",
    cost="local model: one call per endpoint with a known handler, at most 40",
    scope="handler source at the mapped revision; answers are inferences capped at confidence 0.60",
)
LEDGER = ConnectorSpec(
    id="deploy-ledger",
    version=1,
    purpose="which commit each set of running containers was deployed from, and how that is known",
    discovers=["deployment"],
    capability="runtime.read",
    cost="local: reads the workspace's own deploy records",
    scope="deploys of this compose project observed by Unbidden",
)

PROMETHEUS = ConnectorSpec(
    id="prometheus-metrics",
    version=1,
    purpose="who calls whom in real traffic, and each service's requests, errors, latency and resource use",
    discovers=["calls (observed)", "uses_database (observed)", "calls to hosts outside the project"],
    measures=["requests", "error ratio", "p95 latency", "container cpu", "container memory"],
    capability="runtime.read",
    cost="local: about ten instant queries per map, fixed templates, 5 s timeout each",
    scope="the project's own Prometheus; only this project's services and containers are taken in",
)

JAEGER = ConnectorSpec(
    id="jaeger-traces",
    version=1,
    purpose="where failing requests actually fail, to confirm or contradict where metrics say a degradation starts",
    discovers=["failure origins per service"],
    capability="runtime.read",
    cost="local: one trace search per anomaly, at most 100 traces of the last 5 minutes",
    scope="the project's own Jaeger; only service names, span ids and status codes are kept, attributes dropped",
)

CONNECTORS: tuple[ConnectorSpec, ...] = (
    GIT_STATIC,
    COMPOSE_DOCKER,
    OPENAPI_HTTP,
    POSTGRES_READONLY,
    LLM_RELATIONS,
    LEDGER,
    PROMETHEUS,
    JAEGER,
)

# Sources that, when they did not run, leave the system unobserved rather than empty.
NOT_COVERED = {
    "metrics": "no metrics connector (Prometheus, OpenTelemetry, docker stats): resource use and saturation unseen",
    "traces": "no trace connector: which queries and downstream calls a request makes is inferred, never observed",
    "logs": "service logs are read only by investigations and Forge, not into the World Model",
}
