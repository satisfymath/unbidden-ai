"""A source is a workspace in one of three modes, served under the same contracts.

- `demo`: fixtures built through the engine's contracts into an in-memory store; labelled as such everywhere.
- `historical`: a published record (`docs/bench/...`) loaded into an in-memory store, with the record's own times;
  nothing in it is ever presented as current.
- `live`: a real workspace directory, its state opened read-only (`reader.py`); events stream by `seq`.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from unbidden.config import Config, load_config
from unbidden.contracts.common import EvidenceLevel, EvidenceRef
from unbidden.contracts.experiment import Experiment
from unbidden.contracts.guardian import Mandate
from unbidden.contracts.llm import Tier
from unbidden.contracts.opportunity import Opportunity, OpportunityStatus
from unbidden.contracts.world import Deployment
from unbidden.guardian.killswitch import KillSwitch
from unbidden.guardian.mandate import load_mandate
from unbidden.store import Store
from unbidden.web.contracts import SCHEMA, Freshness, Mode, Provenance
from unbidden.web.reader import ReadOnlyStore

CHARGED = "CASE WHEN status IN ('settled', 'failed', 'released') THEN COALESCE(usd, est_usd) ELSE est_usd END"


class SourceError(RuntimeError):
    pass


@dataclass
class Source:
    id: str
    name: str
    mode: Mode
    store: Store
    repo: Path | None = None
    state_dir: Path | None = None  # the workspace's `.unbidden/` in live mode
    mandate: Mandate | None = None
    config: Config | None = None
    observed_at: datetime | None = None  # a record's own time (historical)
    activity_override: dict[str, Any] | None = None  # a record's activity.json, served as the engine wrote it
    timeline: list[dict[str, Any]] = field(default_factory=list)  # a record's cycle log, parsed
    spend_fixture: list[dict[str, Any]] | None = None
    notes: list[str] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock)
    streams: bool = False  # whether new events may arrive (live, and the demo's ticker)

    # Provenance -----------------------------------------------------------------------------------------------

    @property
    def freshness(self) -> Freshness:
        return {"demo": "demo", "historical": "historical", "live": "current"}[self.mode]  # type: ignore[return-value]

    def provenance(self, *, scope: str | None = None, note: str | None = None) -> Provenance:
        return Provenance(
            source=self.id,
            mode=self.mode,
            scope=scope,
            observed_at=self.observed_at or datetime.now(UTC),
            freshness=self.freshness,
            note=note,  # type: ignore[arg-type]
        )

    # Reads ----------------------------------------------------------------------------------------------------

    def head(self) -> str | None:
        value = self.store.get_value("head")
        return str(value) if value else None

    def last_seq(self) -> int:
        if isinstance(self.store, ReadOnlyStore):
            return self.store.last_seq()
        row = self.store._conn.execute("SELECT MAX(seq) FROM events").fetchone()
        return int(row[0] or 0)

    def event_types(self) -> dict[str, int]:
        rows = self.store._conn.execute("SELECT type, COUNT(*) FROM events GROUP BY type")
        return {r[0]: int(r[1]) for r in rows}

    def count(self, collection: str) -> int:
        row = self.store._conn.execute("SELECT COUNT(*) FROM docs WHERE collection = ?", (collection,)).fetchone()
        return int(row[0])

    def job_counts(self) -> dict[str, int]:
        rows = self.store._conn.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status")
        return {r[0]: int(r[1]) for r in rows}

    def round_targets(self) -> list[str]:
        return self.store.round_targets()

    def spend_rows(self) -> list[dict[str, Any]]:
        """This workspace's rows of the machine's ledger, read without opening it for writing."""
        if self.spend_fixture is not None:
            return self.spend_fixture
        from unbidden.brain.spend import home

        path = home() / "spend.db"
        if not path.exists() or self.mandate is None:
            return []
        try:
            with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as db:
                db.row_factory = sqlite3.Row
                return [
                    dict(r)
                    for r in db.execute(
                        f"SELECT *, {CHARGED} AS charged FROM requests WHERE workspace = ? ORDER BY created_at",
                        (self.mandate.workspace,),
                    )
                ]
        except sqlite3.DatabaseError:
            return []

    def killswitch(self) -> KillSwitch | None:
        return KillSwitch(self.state_dir) if self.state_dir is not None else None

    # The summary ----------------------------------------------------------------------------------------------

    def activity(self) -> dict[str, Any]:
        if self.activity_override is not None:
            return self.activity_override
        from unbidden.director.activity import build

        name = self.mandate.workspace if self.mandate else self.name
        return build(self.store, name, self.spend_rows())

    def capabilities(self) -> list[str]:
        caps = []
        if self.count("experiments"):
            caps.append("experiments")
        if self.count("world"):
            caps.append("world")
        if self.count("connections"):
            caps.append("connections")
        if self.round_targets():
            caps.append("probes")
        if self.store.get_value("baseline_checks"):
            caps.append("checks")
        if self.count("proposals"):
            caps.append("proposals")
        if self.count("goal_runs"):
            caps.append("goals")
        if self.count("needs") or self.count("blocks"):
            caps.append("needs")
        if any(t.startswith("anomaly.") for t in self.event_types()):
            caps.append("anomalies")
        if self.count("deployments"):
            caps.append("deployments")
        if self.count("acceptances") or self.count("actions"):
            caps.append("acceptance")
        act = self.activity_override or {}
        for key, cap in (
            ("connections", "connections"),
            ("integrations", "integrations"),
            ("goals", "goals"),
            ("proven", "experiments"),
            ("project_checks", "checks"),
        ):
            if act.get(key) and cap not in caps:
                caps.append(cap)
        return caps

    def route_info(self) -> dict[str, Any]:
        """Where inference runs, said apart from where the server runs: a local server is not a local model."""
        config = self.config or load_config(None)
        local = config.routing.get(Tier.LOCAL)
        code = config.routing.get(Tier.CODE)
        profile = self.mandate.models.profile if self.mandate else "local-first"
        remote_key_file = any(
            p.exists()
            for p in [
                self.state_dir / ".env" if self.state_dir else Path("/nonexistent"),
                Path.home() / ".unbidden" / ".env",
            ]
        )
        from unbidden.guardian.credentials import broker

        remote_provider = config.providers.get(code.provider) if code and code.provider in config.providers else None
        key_env = (remote_provider.key_env if remote_provider else None) or "MODEL_API_KEY"
        key_present = self.mode == "live" and broker().has(key_env)  # a live workspace loads its .env; records never
        local_url = config.providers[local.provider].base_url if local and local.provider in config.providers else None
        return {
            "server": "local",
            "profile": profile,
            "local": {
                "provider": local.provider if local else None,
                "model": local.model if local else None,
                "base_url": local_url,
                "reachable": local_reachable(local_url) if local_url else False,
            },
            "remote": {
                "provider": code.provider if code else None,
                "model": code.model if code else None,
                "credential_file_present": remote_key_file,
                "key_present": key_present,
            },
            "local_inference": self.mandate.models.local_inference if self.mandate else "allow",
            "local_fallback": self.mandate.models.local_fallback if self.mandate else "allow",
            "note": "the server runs on this machine; the model runs where the route says",
        }

    def autonomy_info(self) -> dict[str, Any]:
        if self.mandate is None:
            return {"level": "unknown", "detail": "no mandate in this source", "fields": {}}
        a = self.mandate.autonomy
        fields = {k: str(getattr(a, k)) for k in type(a).model_fields}
        if a.run_experiments == "deny":
            level = "observe-only"
        elif a.open_pull_requests == "allow" or a.deploy == "allow" or a.merge_pull_requests == "allow":
            level = "autonomous"
        else:
            level = "supervised"
        return {
            "level": level,
            "fields": fields,
            "spend_cap_usd": self.mandate.business_constraints.maximum_monthly_spend_usd,
        }

    def highlights(self, limit: int = 4) -> list[dict[str, Any]]:
        """The opportunities worth a card first: by level, then by having an experiment, then by priority."""
        from unbidden.contracts.opportunity import Opportunity

        opps = self.store.list("opportunities", Opportunity)
        experiments = {e.opportunity_id for e in self.store.list("experiments", Experiment)}

        def key(o: Opportunity) -> tuple[int, int, float]:
            return (-int(o.evidence_level), 0 if o.id in experiments else 1, -o.priority_score)

        return [
            {
                "id": o.id,
                "title": o.title,
                "level": int(o.evidence_level),
                "status": o.status.value,
                "has_experiment": o.id in experiments,
            }
            for o in sorted(opps, key=key)[:limit]
        ]

    def summary(self) -> dict[str, Any]:
        with self.lock:
            activity = self.activity()
            kill = self.killswitch()
            counts = {
                "opportunities": self.count("opportunities"),
                "experiments": self.count("experiments"),
                "proposals": self.count("proposals"),
                "events": self.last_seq(),
                "model_runs": self.count("model_runs"),
                "connections": self.count("connections"),
                "deployments": self.count("deployments"),
                "needs": self.count("needs"),
                "blocks": self.count("blocks"),
                "spend_calls": len(self.spend_rows()),
                "world": self.count("world"),
            }
            return {
                "schema": SCHEMA,
                "workspace": {
                    "id": self.id,
                    "name": self.name,
                    "repo": str(self.repo) if self.repo else None,
                    "mode": self.mode,
                    "head": self.head(),
                    "schema_version": getattr(self.store, "schema_version", 2),
                    "notes": self.notes,
                },
                "connection": {
                    "route": self.route_info(),
                    "autonomy": self.autonomy_info(),
                    "kill_switch": kill.engaged if kill else None,
                    "streams": self.streams,
                },
                "activity": activity,
                "counts": counts,
                "jobs": self.job_counts(),
                "capabilities": self.capabilities(),
                "highlights": self.highlights(),
                "timeline_lines": len(self.timeline),
                "observed_at": (self.observed_at or datetime.now(UTC)).isoformat(),
                "freshness": self.freshness,
                "last_event_seq": self.last_seq(),
            }


# Constructors ------------------------------------------------------------------------------------------------


_LOCAL_PROBE: dict[str, tuple[float, bool]] = {}
LOCAL_PROBE_TTL_S = 30.0


def local_reachable(base_url: str) -> bool:
    """Whether the local model server answers, remembered for a short while: shown in the route and used by the
    `auto` planner; a server that comes up later is seen on the next probe, never cached as absent for good."""
    import time

    import httpx

    now = time.monotonic()
    cached = _LOCAL_PROBE.get(base_url)
    if cached and now - cached[0] < LOCAL_PROBE_TTL_S:
        return cached[1]
    try:
        ok = httpx.get(f"{base_url}/api/tags", timeout=2).status_code == 200
    except httpx.HTTPError:
        ok = False
    _LOCAL_PROBE[base_url] = (now, ok)
    return ok


def live(repo: Path, *, id_: str | None = None) -> Source:
    repo = repo.expanduser().resolve()
    state_dir = repo / ".unbidden"
    if not (state_dir / "state.db").exists():
        raise SourceError(f"{repo} has no .unbidden/state.db (run `unbidden init` and a scan there first)")
    store = ReadOnlyStore(state_dir / "state.db")
    mandate = load_mandate(state_dir / "mandate.yaml") if (state_dir / "mandate.yaml").exists() else None
    config = load_config(state_dir / "config.yaml")
    if mandate is not None:
        # The workspace's credentials into the broker (never the environment), granted by purpose as the engine
        # does: a chat routed to Meta's API sends the key the mandate names; records and the demo load nothing.
        from unbidden.workspace import Workspace

        Workspace(repo).load_env()
    notes = []
    if (state_dir / "web-dev-seed").exists():
        notes.append("development workspace: its records were written by this branch's seed, not by a run")
    return Source(
        id=id_ or f"live:{repo.name}",
        name=repo.name,
        mode="live",
        store=store,
        repo=repo,
        state_dir=state_dir,
        mandate=mandate,
        config=config,
        notes=notes,
        streams=True,
    )


LOG_LINE = re.compile(r"^(?P<time>\d\d:\d\d:\d\d) (?P<text>.*)$")
CYCLE = re.compile(r"^== cycle (?P<n>\d+) \((?P<how>[^)]*)\)")


def parse_cycles(text: str, day: str) -> list[dict[str, Any]]:
    """A benchmark's cycle log as a timeline: one entry per logged line, continuation lines folded in."""
    out: list[dict[str, Any]] = []
    cycle = 0
    for line in text.splitlines():
        m = CYCLE.match(line)
        if m:
            cycle = int(m.group("n"))
            out.append({"ts": None, "cycle": cycle, "text": f"cycle {cycle} ({m.group('how')})", "kind": "cycle"})
            continue
        m = LOG_LINE.match(line)
        if m:
            out.append({"ts": f"{day}T{m.group('time')}", "cycle": cycle, "text": m.group("text"), "kind": "log"})
        elif out and line.strip():
            out[-1]["text"] = (out[-1]["text"] + " " + line.strip())[:2000]
    return out


def _record_opportunities(store: Store, activity: dict[str, Any], locator: str) -> None:
    """The proven and experimenting opportunities a summary names, as records; declined ones are counts only."""
    for p in activity.get("proven") or []:
        store.put(
            "opportunities",
            Opportunity(
                id=p["id"],
                source="record",
                category="recorded",
                title=p["title"][:200],
                summary=f"{p['title']} (level L{p['level']} {p.get('level_name', '')}, from the published record)",
                dedup_key=p["id"],
                evidence_level=EvidenceLevel(int(p["level"])),
                status=OpportunityStatus(p["status"])
                if p.get("status") in list(OpportunityStatus)
                else OpportunityStatus.OPEN,
                evidence=[EvidenceRef(kind="analyzer_report", locator=locator, note="activity.json of a closed run")],
                details={
                    "outcome": {"result": p.get("outcome")} if p.get("outcome") else {},
                    "recorded": {k: p.get(k) for k in ("held_checks", "current_rules", "pending_revalidation")},
                },
            ),
            key=p["id"],
        )


def historical(path: Path, *, id_: str | None = None) -> Source:
    """A published record: a run directory (`record.json`, `activity.json`, `cycles.log`, `rounds-*.json`,
    `deployments.jsonl`) or a revalidation file (`experiment` and `verdict` inside)."""
    path = path.expanduser().resolve()
    if not path.exists():
        raise SourceError(f"{path} does not exist")
    store = Store(None)
    notes = ["historical record: a closed run; nothing here is current"]
    if path.is_file():
        data = json.loads(path.read_text())
        if "experiment" not in data or "verdict" not in data:
            raise SourceError(f"{path}: not a revalidation record (no experiment and verdict)")
        exp = Experiment.model_validate(data["experiment"])
        store.put("experiments", exp)
        level = int(data.get("level_after", data["verdict"].get("evidence_level", 1)))
        store.put(
            "opportunities",
            Opportunity(
                id=str(data["opportunity"]),
                source="record",
                category="performance",
                title=str(data["title"])[:200],
                summary=f"{data['title']} · revalidated at {str(data.get('product', ''))[:12]}: L{level}",
                dedup_key=str(data["opportunity"]),
                evidence_level=EvidenceLevel(max(1, min(6, level))),
                status=OpportunityStatus.VERIFIED if level >= 4 else OpportunityStatus.OPEN,
                evidence=[EvidenceRef(kind="experiment", locator=exp.id, note=str(path.name))],
                details={
                    "verdict": data["verdict"],
                    "experiment_id": exp.id,
                    "readiness": data.get("readiness"),
                    "notes": data.get("notes"),
                    "original_level": data.get("original_level"),
                    "blocked": {"why": data["blocked"]} if data.get("blocked") else None,
                },
            ),
            key=str(data["opportunity"]),
        )
        if data.get("base"):
            store.set_value("head", data["base"])
        store.set_value("web_record", {"path": str(path), "name": data.get("name")})
        name = str(data.get("name") or path.stem)
        return Source(
            id=id_ or f"record:{name}",
            name=name,
            mode="historical",
            store=store,
            observed_at=exp.started_at,
            notes=[*notes, f"base {str(data.get('base', ''))[:12]}, product {str(data.get('product', ''))[:12]}"],
            spend_fixture=[],
        )
    activity = None
    observed: datetime | None = None
    name = path.name
    if (path / "activity.json").exists():
        activity = json.loads((path / "activity.json").read_text())
        observed = datetime.fromisoformat(activity["at"])
        name = f"{activity.get('workspace', path.name)} · {path.name}"
        _record_opportunities(store, activity, str(path / "activity.json"))
        checks = activity.get("project_checks")
        if checks:
            store.set_value("baseline_checks", checks)
    if (path / "record.json").exists():
        record = json.loads((path / "record.json").read_text())
        commit = (record.get("restored") or {}).get("commit")
        if commit:
            store.set_value("head", commit)
        notes.append(
            f"run {record.get('run', path.name)}, mode {record.get('mode', '?')}, {record.get('wall_s', '?')} s"
        )
        store.set_value("web_record", {"path": str(path), "run": record.get("run")})
    timeline: list[dict[str, Any]] = []
    if (path / "cycles.log").exists():
        day = (observed or datetime.now(UTC)).date().isoformat()
        timeline = parse_cycles((path / "cycles.log").read_text(errors="replace"), day)
    for rounds_file in sorted(path.glob("rounds-*.json")):
        for r in json.loads(rounds_file.read_text()):
            store._conn.execute(
                "INSERT INTO rounds (ts, target, version, statuses, latencies, deploy) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    r["ts"],
                    r.get("target") or rounds_file.stem.removeprefix("rounds-"),
                    r["version"],
                    r["statuses"] if isinstance(r["statuses"], str) else json.dumps(r["statuses"]),
                    r["latencies"] if isinstance(r["latencies"], str) else json.dumps(r["latencies"]),
                    int(r.get("deploy", -1)),
                ),
            )
            observed = observed or datetime.fromisoformat(r["ts"])
    if (path / "deployments.jsonl").exists():
        for line in (path / "deployments.jsonl").read_text().splitlines():
            if line.strip():
                try:
                    store.put("deployments", Deployment.model_validate_json(line))
                except ValueError as exc:
                    notes.append(f"a deployment line could not be read: {str(exc)[:80]}")
    for extra in ("deploy-verdict.json", "outcome.json"):
        if (path / extra).exists():
            text = (path / extra).read_text()
            try:  # some records open with a one-line summary before the JSON
                data = json.loads(text) if text.lstrip().startswith("{") else json.loads(text[text.index("{") :])
                store.set_value(f"web_record:{extra.removesuffix('.json')}", data)
                if extra == "outcome.json" and text.lstrip()[0] != "{":
                    notes.append(text.splitlines()[0][:160])
            except ValueError:
                notes.append(f"{extra} is not JSON")
    if activity is None and not timeline and not store.round_targets():
        raise SourceError(f"{path}: no activity.json, cycles.log or rounds-*.json found")
    spend = []
    if activity and activity.get("spent"):
        spend = []  # the summary keeps the total; the ledger rows were not published
    return Source(
        id=id_ or f"record:{path.name}",
        name=name,
        mode="historical",
        store=store,
        observed_at=observed,
        activity_override=activity,
        timeline=timeline,
        notes=notes,
        spend_fixture=spend,
    )


def demo() -> Source:
    from unbidden.web.demo import build_demo

    return build_demo()
