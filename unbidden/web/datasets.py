"""The dataset catalogue: every series a widget may show, resolved from the engine's records with its provenance.

A `DataRef` names a dataset and a bounded transform (select, filter, group, aggregate, sort, limit). No SQL and no
code arrive from the browser. Each dataset says what it is made of; a dataset that has no rows says why.
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from unbidden.contracts.common import EvidenceRef
from unbidden.contracts.connection import Connection
from unbidden.contracts.experiment import Experiment, Proposal
from unbidden.contracts.llm import ModelRun
from unbidden.contracts.opportunity import Opportunity
from unbidden.contracts.world import Deployment, WorldModel
from unbidden.director.activity import level_name, live_criteria
from unbidden.web.contracts import Column, DataRef, DataResult, Transform

if TYPE_CHECKING:
    from unbidden.web.sources import Source

Rows = list[dict[str, Any]]
Resolver = Callable[["Source", dict[str, Any]], tuple[list[Column], Rows, str | None]]


class DatasetError(ValueError):
    pass


@dataclass(frozen=True)
class Dataset:
    id: str
    title: str
    fields: list[Column]
    params: list[str]
    resolve: Resolver
    unit: str | None = None
    scope: str = "workspace"


CATALOGUE: dict[str, Dataset] = {}


def dataset(
    id_: str,
    title: str,
    fields: list[tuple[str, str, str | None]],
    params: list[str] | None = None,
    unit: str | None = None,
    scope: str = "workspace",
) -> Callable[[Resolver], Resolver]:
    def register(fn: Resolver) -> Resolver:
        CATALOGUE[id_] = Dataset(
            id_,
            title,
            [Column.model_validate({"name": n, "type": t, "unit": u}) for n, t, u in fields],
            params or [],
            fn,
            unit,
            scope,  # type: ignore[arg-type]
        )
        return fn

    return register


def catalogue() -> list[dict[str, Any]]:
    return [
        {
            "id": d.id,
            "title": d.title,
            "fields": [c.model_dump(mode="json") for c in d.fields],
            "params": d.params,
            "unit": d.unit,
            "scope": d.scope,
        }
        for d in CATALOGUE.values()
    ]


# Resolution --------------------------------------------------------------------------------------------------


def resolve(source: Source, ref: DataRef) -> DataResult:
    spec = CATALOGUE.get(ref.dataset)
    if spec is None:
        raise DatasetError(f"unknown dataset {ref.dataset!r}; see /api/datasets")
    unknown = set(ref.params) - set(spec.params)
    if unknown:
        raise DatasetError(f"{ref.dataset} takes no parameter {', '.join(sorted(unknown))}")
    with source.lock:
        columns, rows, note = spec.resolve(source, dict(ref.params))
    total = len(rows)
    rows, columns = apply_transform(rows, columns, ref.transform)
    truncated = total > len(rows) and ref.transform.group_by is None
    prov = source.provenance(scope=_scope(ref), note=note)
    if not rows and total == 0:
        if ref.params:
            # Asked about one thing (an experiment, a run) and the record holds nothing for it: not available.
            prov.completeness = "missing"
            prov.note = note or f"{spec.title}: the record holds nothing for this request"
        else:
            # The whole collection was read and it is empty: a complete read of zero rows, not missing data.
            prov.completeness = "complete"
            prov.note = note or f"{spec.title}: zero rows in this record"
    elif not rows:  # the transform filtered every row out: the read was complete
        prov.note = note or f"{spec.title}: {total} row(s) in the record, none match this request"
    elif truncated:
        prov.completeness, prov.limit = "partial", ref.transform.limit
    return DataResult(columns=columns, rows=rows, provenance=prov, truncated=truncated, total=total)


def _scope(ref: DataRef) -> str:
    return ", ".join(f"{k}={v}" for k, v in ref.params.items()) or "workspace"


def _value(row: dict[str, Any], field: str) -> Any:
    return row.get(field)


def _matches(row: dict[str, Any], flt: Any) -> bool:
    v = _value(row, flt.field)
    w = flt.value
    match flt.op:
        case "eq":
            return v == w
        case "ne":
            return v != w
        case "gt":
            return v is not None and w is not None and v > w
        case "lt":
            return v is not None and w is not None and v < w
        case "gte":
            return v is not None and w is not None and v >= w
        case "lte":
            return v is not None and w is not None and v <= w
        case "in":
            return isinstance(w, list) and v in w
        case "contains":
            return isinstance(v, str) and isinstance(w, str) and w.lower() in v.lower()
    return False


def _aggregate(values: list[Any], fn: str) -> float | int | None:
    nums = [float(v) for v in values if isinstance(v, int | float) and not isinstance(v, bool)]
    if fn == "count":
        return len(values)
    if not nums:
        return None
    match fn:
        case "sum":
            return sum(nums)
        case "mean":
            return statistics.fmean(nums)
        case "median":
            return statistics.median(nums)
        case "p95":
            s = sorted(nums)
            return s[min(len(s) - 1, round(0.95 * (len(s) - 1)))]
        case "min":
            return min(nums)
        case "max":
            return max(nums)
    return None


def apply_transform(rows: Rows, columns: list[Column], t: Transform) -> tuple[Rows, list[Column]]:
    names = {c.name for c in columns}
    for flt in t.filter:
        if flt.field not in names:
            raise DatasetError(f"no field {flt.field!r}; fields: {', '.join(sorted(names))}")
    out = [r for r in rows if all(_matches(r, f) for f in t.filter)]
    if t.group_by is not None:
        if t.group_by not in names:
            raise DatasetError(f"cannot group by {t.group_by!r}")
        agg = t.aggregate
        if agg is not None and agg.field not in names:
            raise DatasetError(f"cannot aggregate {agg.field!r}")
        groups: dict[Any, list[dict[str, Any]]] = {}
        for r in out:
            groups.setdefault(r.get(t.group_by), []).append(r)
        fn = agg.fn if agg else "count"
        field = agg.field if agg else t.group_by
        label = f"{fn}_{field}" if agg else "count"
        out = [{t.group_by: k, label: _aggregate([g.get(field) for g in grp], fn)} for k, grp in groups.items()]
        gcol = next(c for c in columns if c.name == t.group_by)
        unit = next((c.unit for c in columns if c.name == field), None) if fn != "count" else None
        columns = [gcol, Column(name=label, type="number", unit=unit)]
        names = {c.name for c in columns}
    if t.sort is not None:
        if t.sort.field not in names:
            raise DatasetError(f"cannot sort by {t.sort.field!r}")
        key = t.sort.field
        out.sort(
            key=lambda r: (r.get(key) is None, r.get(key) if r.get(key) is not None else 0),
            reverse=t.sort.dir == "desc",
        )
    if t.select:
        missing = [s for s in t.select if s not in names]
        if missing:
            raise DatasetError(f"no field {', '.join(missing)}")
        out = [{k: r.get(k) for k in t.select} for r in out]
        columns = [c for c in columns if c.name in t.select]
    return out[: t.limit], columns


# Datasets ----------------------------------------------------------------------------------------------------


def _iso(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() if isinstance(value, datetime) else str(value)


@dataset(
    "opportunities",
    "Opportunities: what was found, its level and the Director's decision",
    [
        ("id", "string", None),
        ("title", "string", None),
        ("source", "string", None),
        ("category", "string", None),
        ("status", "string", None),
        ("level", "number", "L"),
        ("level_name", "string", None),
        ("live_criteria", "string", None),
        ("decision", "string", None),
        ("reason", "string", None),
        ("experiment_id", "string", None),
        ("created_at", "datetime", None),
        ("updated_at", "datetime", None),
    ],
)
def _opportunities(source: Source, params: dict[str, Any]) -> tuple[list[Column], Rows, str | None]:
    rows = []
    for o in source.store.list("opportunities", Opportunity):
        d = o.details.get("decision") or {}
        rows.append(
            {
                "id": o.id,
                "title": o.title,
                "source": o.source,
                "category": o.category,
                "status": o.status.value,
                "level": int(o.evidence_level),
                "level_name": level_name(o),
                "live_criteria": live_criteria(o),
                "decision": d.get("chosen"),
                "reason": d.get("reason"),
                "experiment_id": (o.details.get("verdict") or {}).get("experiment_id")
                or o.details.get("experiment_id"),
                "created_at": _iso(o.created_at),
                "updated_at": _iso(o.updated_at),
            }
        )
    return CATALOGUE["opportunities"].fields, rows, None


def _experiment(source: Source, params: dict[str, Any]) -> Experiment | None:
    exp_id = params.get("experiment_id")
    if exp_id:
        return source.store.get("experiments", str(exp_id), Experiment)
    opp_id = params.get("opportunity_id")
    experiments = source.store.list("experiments", Experiment)
    if opp_id:
        experiments = [e for e in experiments if e.opportunity_id == opp_id]
    return experiments[-1] if experiments else None


@dataset(
    "experiment.samples",
    "Latency samples of an experiment, before and after the change",
    [
        ("arm", "string", None),
        ("i", "number", None),
        ("ms", "number", "ms"),
        ("session", "number", None),
        ("phase", "string", None),
    ],
    params=["experiment_id", "opportunity_id"],
    unit="ms",
    scope="experiment",
)
def _samples(source: Source, params: dict[str, Any]) -> tuple[list[Column], Rows, str | None]:
    exp = _experiment(source, params)
    cols = CATALOGUE["experiment.samples"].fields
    if exp is None:
        return cols, [], "no experiment matches; run one first (`unbidden try <opportunity>`)"
    rows: Rows = []
    for phase, sessions in (("measured", exp.sessions), ("control", exp.control), ("confirmation", exp.confirmation)):
        for s in sessions:
            arm = "before" if s.get("arm") in ("base", "baseline", "before") else "after"
            for i, ms in enumerate(s.get("samples_ms") or s.get("samples") or []):
                rows.append({"arm": arm, "i": i, "ms": float(ms), "session": s.get("position"), "phase": phase})
    if not rows:
        for arm, samples in (("before", exp.samples_before_ms), ("after", exp.samples_after_ms)):
            rows += [
                {"arm": arm, "i": i, "ms": float(ms), "session": None, "phase": "measured"}
                for i, ms in enumerate(samples)
            ]
    note = None if rows else f"experiment {exp.id} recorded no samples (its verdict may be blocked or inconclusive)"
    return cols, rows, note


@dataset(
    "experiment.sessions",
    "Session medians of an experiment (criteria perf-v3/v4)",
    [
        ("arm", "string", None),
        ("position", "number", None),
        ("median_ms", "number", "ms"),
        ("n", "number", None),
        ("phase", "string", None),
        ("index_scans", "number", None),
    ],
    params=["experiment_id", "opportunity_id"],
    unit="ms",
    scope="experiment",
)
def _sessions(source: Source, params: dict[str, Any]) -> tuple[list[Column], Rows, str | None]:
    exp = _experiment(source, params)
    cols = CATALOGUE["experiment.sessions"].fields
    if exp is None:
        return cols, [], "no experiment matches"
    rows: Rows = []
    for phase, sessions in (("measured", exp.sessions), ("control", exp.control), ("confirmation", exp.confirmation)):
        for s in sessions:
            samples = s.get("samples_ms") or s.get("samples") or []
            median = s.get("median_ms", s.get("median"))
            if median is None and samples:
                median = statistics.median(samples)
            rows.append(
                {
                    "arm": "before" if s.get("arm") in ("base", "baseline", "before") else "after",
                    "position": s.get("position"),
                    "median_ms": median,
                    "n": len(samples),
                    "phase": phase,
                    "index_scans": s.get("index_scans"),
                }
            )
    return cols, rows, None if rows else f"experiment {exp.id} has no sessions (older criteria, or not measured)"


@dataset(
    "experiment.compare",
    "Session medians of two experiments side by side (compatible runs only)",
    [
        ("experiment", "string", None),
        ("arm", "string", None),
        ("position", "number", None),
        ("median_ms", "number", "ms"),
        ("phase", "string", None),
    ],
    params=["experiment_a", "experiment_b"],
    unit="ms",
    scope="experiment",
)
def _compare(source: Source, params: dict[str, Any]) -> tuple[list[Column], Rows, str | None]:
    cols = CATALOGUE["experiment.compare"].fields
    pair = [
        source.store.get("experiments", str(params.get(k) or ""), Experiment) for k in ("experiment_a", "experiment_b")
    ]
    if any(e is None for e in pair):
        return cols, [], "both experiments must exist in this workspace"
    a, b = pair[0], pair[1]
    assert a is not None and b is not None
    if a.workload_sha256 and b.workload_sha256 and a.workload_sha256 != b.workload_sha256:
        return (
            cols,
            [],
            (
                f"the runs are not compatible: different workloads ({a.workload_sha256[:8]} vs "
                f"{b.workload_sha256[:8]}); a comparison would compare two different measurements"
            ),
        )
    rows: Rows = []
    for exp in (a, b):
        _, sessions, _ = _sessions(source, {"experiment_id": exp.id})
        rows += [
            {"experiment": exp.id, **{k: s[k] for k in ("arm", "position", "median_ms", "phase")}} for s in sessions
        ]
    return cols, rows, None if rows else "neither experiment holds sessions"


@dataset(
    "experiment.tests",
    "Test rounds of an experiment on both sides",
    [
        ("arm", "string", None),
        ("round", "number", None),
        ("status", "string", None),
        ("collected", "number", None),
        ("failed", "number", None),
        ("failed_tests", "json", None),
    ],
    params=["experiment_id", "opportunity_id"],
    scope="experiment",
)
def _tests(source: Source, params: dict[str, Any]) -> tuple[list[Column], Rows, str | None]:
    exp = _experiment(source, params)
    cols = CATALOGUE["experiment.tests"].fields
    if exp is None:
        return cols, [], "no experiment matches"
    rows: Rows = []
    for arm, summary in (("before", exp.baseline_tests), ("after", exp.candidate_tests)):
        if summary is None:
            continue
        for i, failed in enumerate(summary.failed_per_round):
            collected = summary.collected_per_round[i] if i < len(summary.collected_per_round) else None
            rows.append(
                {
                    "arm": arm,
                    "round": i + 1,
                    "status": summary.status(i),
                    "collected": collected,
                    "failed": len(failed),
                    "failed_tests": failed,
                }
            )
    return cols, rows, None if rows else f"experiment {exp.id} ran no test suite (tests: not run)"


@dataset(
    "tests.failed",
    "Tests that failed in any experiment round, by side",
    [
        ("experiment_id", "string", None),
        ("opportunity_id", "string", None),
        ("arm", "string", None),
        ("round", "number", None),
        ("test", "string", None),
    ],
    params=["experiment_id", "opportunity_id"],
    scope="experiment",
)
def _failed(source: Source, params: dict[str, Any]) -> tuple[list[Column], Rows, str | None]:
    experiments = source.store.list("experiments", Experiment)
    if params.get("experiment_id"):
        experiments = [e for e in experiments if e.id == params["experiment_id"]]
    if params.get("opportunity_id"):
        experiments = [e for e in experiments if e.opportunity_id == params["opportunity_id"]]
    rows: Rows = []
    for exp in experiments:
        for arm, summary in (("before", exp.baseline_tests), ("after", exp.candidate_tests)):
            for i, failed in enumerate(summary.failed_per_round if summary else []):
                rows += [
                    {
                        "experiment_id": exp.id,
                        "opportunity_id": exp.opportunity_id,
                        "arm": arm,
                        "round": i + 1,
                        "test": t,
                    }
                    for t in failed
                ]
    note = None
    if not rows:
        ran = any(e.baseline_tests or e.candidate_tests for e in experiments)
        note = "no test failed in any recorded round" if ran else "no experiment recorded a test run"
    return CATALOGUE["tests.failed"].fields, rows, note


@dataset(
    "probe.rounds",
    "Live probe rounds: latency and status per round, by target and deploy",
    [
        ("ts", "datetime", None),
        ("target", "string", None),
        ("version", "string", None),
        ("deploy", "number", None),
        ("n", "number", None),
        ("p50_ms", "number", "ms"),
        ("p95_ms", "number", "ms"),
        ("errors", "number", None),
    ],
    params=["target", "deploy", "version"],
    unit="ms",
    scope="deploy",
)
def _rounds(source: Source, params: dict[str, Any]) -> tuple[list[Column], Rows, str | None]:
    conn = source.store._conn
    sql, args = "SELECT ts, target, version, statuses, latencies, deploy FROM rounds WHERE 1=1", []
    for key in ("target", "version"):
        if params.get(key):
            sql += f" AND {key} = ?"
            args.append(params[key])
    if params.get("deploy") is not None:
        sql += " AND deploy = ?"
        args.append(int(params["deploy"]))
    rows: Rows = []
    for r in conn.execute(sql + " ORDER BY ts LIMIT 20000", args):
        lat = sorted(float(x) for x in json.loads(r[4]))
        st = json.loads(r[3])
        p50 = statistics.median(lat) if lat else None
        p95 = lat[min(len(lat) - 1, round(0.95 * (len(lat) - 1)))] if lat else None
        rows.append(
            {
                "ts": r[0],
                "target": r[1],
                "version": str(r[2])[:12],
                "deploy": r[5],
                "n": len(lat),
                "p50_ms": p50,
                "p95_ms": p95,
                "errors": sum(1 for s in st if int(s) >= 500),
            }
        )
    note = None if rows else "no probe round recorded: probes run only with a mandate that declares operations"
    return CATALOGUE["probe.rounds"].fields, rows, note


@dataset(
    "spend.calls",
    "Remote model calls charged to this workspace (the machine's ledger)",
    [
        ("created_at", "datetime", None),
        ("run", "string", None),
        ("purpose", "string", None),
        ("model", "string", None),
        ("status", "string", None),
        ("usd", "number", "USD"),
        ("tokens_in", "number", None),
        ("tokens_out", "number", None),
        ("envelope", "string", None),
    ],
    unit="USD",
)
def _spend(source: Source, params: dict[str, Any]) -> tuple[list[Column], Rows, str | None]:
    rows = [
        {
            "created_at": r.get("created_at"),
            "run": r.get("run") or "(no run)",
            "purpose": r.get("purpose"),
            "model": r.get("model"),
            "status": r.get("status"),
            "usd": float(r.get("charged") or 0.0),
            "tokens_in": r.get("tokens_in"),
            "tokens_out": r.get("tokens_out"),
            "envelope": r.get("envelope"),
        }
        for r in source.spend_rows()
    ]
    note = None if rows else "no remote call charged to this workspace in the machine's ledger"
    if not rows and source.activity_override and (source.activity_override.get("spent") or {}).get("calls"):
        spent = source.activity_override["spent"]
        note = (
            f"the published record keeps the total (US${spent.get('usd', 0):.4f} in {spent.get('calls')} calls), "
            "not the ledger rows"
        )
    return CATALOGUE["spend.calls"].fields, rows, note


@dataset(
    "model_runs",
    "Model calls recorded in the workspace: route, model, tokens, cost",
    [
        ("created_at", "datetime", None),
        ("purpose", "string", None),
        ("tier", "string", None),
        ("provider", "string", None),
        ("model", "string", None),
        ("ok", "boolean", None),
        ("tokens_in", "number", None),
        ("tokens_out", "number", None),
        ("usd", "number", "USD"),
        ("route_reason", "string", None),
        ("correlation_id", "string", None),
    ],
    unit="USD",
)
def _model_runs(source: Source, params: dict[str, Any]) -> tuple[list[Column], Rows, str | None]:
    rows = [
        {
            "created_at": _iso(r.created_at),
            "purpose": r.purpose,
            "tier": r.tier.value,
            "provider": r.provider,
            "model": r.model,
            "ok": r.ok,
            "tokens_in": r.cost.tokens_in,
            "tokens_out": r.cost.tokens_out,
            "usd": round(r.cost.usd, 6),
            "route_reason": r.route_reason,
            "correlation_id": r.correlation_id,
        }
        for r in source.store.list("model_runs", ModelRun)
    ]
    return CATALOGUE["model_runs"].fields, rows, None if rows else "no model call recorded in this workspace"


@dataset(
    "events.by_type", "Events in the workspace, counted by type", [("type", "string", None), ("count", "number", None)]
)
def _events_by_type(source: Source, params: dict[str, Any]) -> tuple[list[Column], Rows, str | None]:
    rows = [{"type": t, "count": n} for t, n in sorted(source.event_types().items(), key=lambda x: -x[1])]
    return CATALOGUE["events.by_type"].fields, rows, None if rows else "no event recorded"


@dataset(
    "events",
    "Events, oldest first after a cursor",
    [
        ("seq", "number", None),
        ("ts", "datetime", None),
        ("type", "string", None),
        ("actor", "string", None),
        ("entity_id", "string", None),
        ("correlation_id", "string", None),
        ("payload", "json", None),
    ],
    params=["after", "correlation_id", "type"],
)
def _events(source: Source, params: dict[str, Any]) -> tuple[list[Column], Rows, str | None]:
    after = int(params.get("after") or 0)
    events = source.store.events(after=after, correlation_id=params.get("correlation_id"), limit=2000)
    if params.get("type"):
        events = [e for e in events if e.type.value == params["type"]]
    rows = [
        {
            "seq": e.seq,
            "ts": _iso(e.ts),
            "type": e.type.value,
            "actor": e.actor,
            "entity_id": e.entity_id,
            "correlation_id": e.correlation_id,
            "payload": e.payload,
        }
        for e in events
    ]
    return CATALOGUE["events"].fields, rows, None if rows else "no event after that cursor"


@dataset(
    "world.resources",
    "Resources of the world model, with how each is known",
    [
        ("id", "string", None),
        ("kind", "string", None),
        ("name", "string", None),
        ("status", "string", None),
        ("confidence", "number", None),
        ("source", "string", None),
        ("environment", "string", None),
        ("observed_at", "datetime", None),
        ("valid_for", "string", None),
    ],
)
def _resources(source: Source, params: dict[str, Any]) -> tuple[list[Column], Rows, str | None]:
    world = source.store.get("world", "world", WorldModel)
    cols = CATALOGUE["world.resources"].fields
    if world is None:
        return cols, [], "no world model yet (`unbidden map` builds it from the repository and what runs)"
    rows = [
        {
            "id": r.id,
            "kind": r.kind,
            "name": r.name,
            "status": r.status.value,
            "confidence": r.confidence,
            "source": r.source,
            "environment": r.environment,
            "observed_at": _iso(r.observed_at),
            "valid_for": r.valid_for,
        }
        for r in world.resources.values()
    ]
    return cols, rows, None


@dataset(
    "world.relations",
    "Relations of the world model, each with its evidence",
    [
        ("src", "string", None),
        ("dst", "string", None),
        ("predicate", "string", None),
        ("status", "string", None),
        ("confidence", "number", None),
        ("source", "string", None),
        ("evidence", "json", None),
    ],
)
def _relations(source: Source, params: dict[str, Any]) -> tuple[list[Column], Rows, str | None]:
    world = source.store.get("world", "world", WorldModel)
    cols = CATALOGUE["world.relations"].fields
    if world is None:
        return cols, [], "no world model yet"
    rows = [
        {
            "src": r.src,
            "dst": r.dst,
            "predicate": r.predicate,
            "status": r.status.value,
            "confidence": r.confidence,
            "source": r.source,
            "evidence": [e.model_dump(mode="json") for e in r.evidence],
        }
        for r in world.current_relations()
    ]
    return cols, rows, None if rows else "the world model holds resources but no relation"


@dataset(
    "connections",
    "Connections: what Unbidden can reach and what was checked",
    [
        ("id", "string", None),
        ("kind", "string", None),
        ("environment", "string", None),
        ("state", "string", None),
        ("read", "json", None),
        ("write", "json", None),
        ("blocked", "string", None),
        ("next_step", "string", None),
        ("checked_at", "datetime", None),
    ],
)
def _connections(source: Source, params: dict[str, Any]) -> tuple[list[Column], Rows, str | None]:
    from unbidden.connect.registry import COLLECTION, summary

    rows = summary(source.store.list(COLLECTION, Connection))
    note = None
    if not rows and source.activity_override and source.activity_override.get("connections"):
        rows = list(source.activity_override["connections"])  # the record's own summary, as the engine wrote it
        note = "from the published summary; the connection documents themselves were not published"
    keep = [c.name for c in CATALOGUE["connections"].fields]
    rows = [{k: r.get(k) for k in keep} for r in rows]
    return CATALOGUE["connections"].fields, rows, note if rows else "no connection surveyed yet"


@dataset(
    "proposals",
    "Proposals and the state of their pull requests",
    [
        ("id", "string", None),
        ("opportunity_id", "string", None),
        ("title", "string", None),
        ("status", "string", None),
        ("level", "number", "L"),
        ("branch", "string", None),
        ("pr", "string", None),
        ("created_at", "datetime", None),
    ],
)
def _proposals(source: Source, params: dict[str, Any]) -> tuple[list[Column], Rows, str | None]:
    rows = [
        {
            "id": p.id,
            "opportunity_id": p.opportunity_id,
            "title": p.title,
            "status": p.status.value,
            "level": int(p.evidence_level),
            "branch": p.branch,
            "pr": p.pr.url if p.pr else None,
            "created_at": _iso(p.created_at),
        }
        for p in source.store.list("proposals", Proposal)
    ]
    return CATALOGUE["proposals"].fields, rows, None if rows else "no proposal yet: nothing reached L4"


@dataset(
    "deployments",
    "Deploys observed: which commit each set of containers ran, and how that is known",
    [
        ("index", "number", None),
        ("environment", "string", None),
        ("commit", "string", None),
        ("commit_status", "string", None),
        ("initiated_by", "string", None),
        ("containers", "number", None),
        ("seen_at", "datetime", None),
        ("reason", "string", None),
    ],
)
def _deployments(source: Source, params: dict[str, Any]) -> tuple[list[Column], Rows, str | None]:
    rows = [
        {
            "index": d.index,
            "environment": d.environment,
            "commit": (d.commit or "")[:12],
            "commit_status": d.commit_status,
            "initiated_by": d.initiated_by,
            "containers": len(d.containers),
            "seen_at": _iso(d.seen_at),
            "reason": d.commit_reason,
        }
        for d in source.store.list("deployments", Deployment)
    ]
    rows.sort(key=lambda r: r["index"])
    return (
        CATALOGUE["deployments"].fields,
        rows,
        None if rows else "no deploy observed (the ledger needs a running compose project)",
    )


@dataset(
    "checks",
    "The project's own checks at the base of each revision",
    [
        ("rev", "string", None),
        ("status", "string", None),
        ("collected", "number", None),
        ("failed", "number", None),
        ("partial", "boolean", None),
        ("why", "string", None),
        ("at", "datetime", None),
    ],
)
def _checks(source: Source, params: dict[str, Any]) -> tuple[list[Column], Rows, str | None]:
    c = source.store.get_value("baseline_checks") or {}
    cols = CATALOGUE["checks"].fields
    if not c:
        return cols, [], "the project's checks were not run here yet"
    return (
        cols,
        [
            {
                "rev": str(c.get("rev", ""))[:12],
                "status": c.get("status"),
                "collected": c.get("collected"),
                "failed": len(c.get("failed") or []),
                "partial": bool(c.get("partial")),
                "why": c.get("why"),
                "at": c.get("at"),
            }
        ],
        None,
    )


@dataset(
    "anomalies",
    "Anomalies detected on the running system, open and resolved",
    [
        ("ts", "datetime", None),
        ("state", "string", None),
        ("entity", "string", None),
        ("kind", "string", None),
        ("detail", "string", None),
    ],
)
def _anomalies(source: Source, params: dict[str, Any]) -> tuple[list[Column], Rows, str | None]:
    rows: Rows = []
    for e in source.store.events(limit=5000):
        if e.type.value in ("anomaly.detected", "anomaly.resolved"):
            p = e.payload
            rows.append(
                {
                    "ts": _iso(e.ts),
                    "state": e.type.value.split(".")[1],
                    "entity": e.entity_id,
                    "kind": p.get("kind") or p.get("signal") or "anomaly",
                    "detail": str(p.get("why") or p.get("detail") or p.get("summary") or "")[:200],
                }
            )
    return CATALOGUE["anomalies"].fields, rows, None if rows else "no anomaly recorded (health needs metrics)"


def evidence_for(opp: Opportunity) -> list[EvidenceRef]:
    return list(opp.evidence)[:6]
