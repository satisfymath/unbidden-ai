"""Remote model spend on this machine, across every workspace, and the gate that keeps it inside a verified budget.

A workspace's monthly cap (the mandate's) counts only that workspace's calls, and only after they are made. A
benchmark opens dozens of workspaces, and promotional credits are one balance for all of them, so this ledger is
shared by every workspace on the machine (`~/.unbidden/spend.db`) and is checked before each call:

- **Reserve before sending.** The worst cost of a call (every payload byte a token, plus `max_tokens` of output, at
  list price) is reserved in one transaction. A call that would not fit is refused before anything leaves.
- **Settle after.** The reservation becomes the cost of the tokens the provider reported. A call that failed in a way
  that may have been billed (a timeout, a 5xx, no usage reported) keeps its worst cost: unknown is never free.
- **The budget is what a person read.** The provider offers no balance API (measured: every billing path is a 404),
  so the remaining balance is entered with `unbidden spend --verified-balance`, with its source and time. Spend is
  counted from that moment. A share is held back as a reserve (20 % by default) that only a person releases. Without
  a verified balance, only a small allowance is spent, enough to check the remote path works.

Costs are list prices times reported tokens: an estimate of what is billed, recorded as such.

**Envelopes** (stage 9): an authorization may be split into named envelopes (development, evaluation, demo), each
with its own cap. Once envelopes are defined, every call names one (`UNBIDDEN_ENVELOPE`) and is refused, before it
leaves, if it does not name a known envelope or would not fit in it; the overall cap still applies. A cap is raised
without moving the point from which spend is counted (`--amend-cap`), so earlier spend keeps counting.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from unbidden.contracts.common import new_id, utc_now

# Every payload byte counted as a token: tokenizers average 3-4 bytes per token on code and English.
BYTES_PER_TOKEN_WORST = 1.0
ENVELOPE_TOKENS = 64


def home() -> Path:
    return Path(os.environ.get("UNBIDDEN_HOME") or Path.home() / ".unbidden")


def run_tag() -> str | None:
    """The experiment this process works for (a benchmark run sets it), so every call is attributed."""
    return os.environ.get("UNBIDDEN_RUN") or None


def envelope_tag() -> str | None:
    """The envelope this process spends from, when the authorization is split into envelopes."""
    return os.environ.get("UNBIDDEN_ENVELOPE") or None


class SpendRefused(RuntimeError):
    pass


class Budget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    remaining_usd: float | None = Field(default=None, ge=0)  # as read on the provider's dashboard
    verified_at: datetime | None = None
    source: str | None = None
    expires_at: datetime | None = None  # credits unusable after this; nothing is spent past it
    reserve_fraction: float = Field(default=0.2, ge=0, lt=1)
    reserve_released: bool = False  # set by a person, for final validation and the demo
    unverified_allowance_usd: float = Field(default=1.0, ge=0)
    envelopes: dict[str, float] = Field(default_factory=dict)  # name -> cap in US$, counted from `envelopes_since`
    envelopes_total_usd: float | None = None  # what the envelopes may add up to (the authorization they split)
    envelopes_since: datetime | None = None

    @property
    def verified(self) -> bool:
        return self.remaining_usd is not None and self.verified_at is not None


@dataclass(frozen=True)
class Status:
    verified: bool
    permitted_usd: float  # what may be spent since `since`, reserve excluded unless released
    spent_usd: float  # settled costs plus open reservations, since `since`
    reserve_usd: float
    since: datetime | None
    expired: bool
    reason: str

    @property
    def available_usd(self) -> float:
        return 0.0 if self.expired else max(0.0, self.permitted_usd - self.spent_usd)


SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    settled_at TEXT,
    workspace TEXT NOT NULL,
    run TEXT,
    purpose TEXT NOT NULL,
    correlation_id TEXT,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    status TEXT NOT NULL,          -- reserved | settled | failed | released
    est_usd REAL NOT NULL,
    usd REAL,
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    usage_reported INTEGER NOT NULL DEFAULT 0,
    note TEXT,
    envelope TEXT
);
CREATE INDEX IF NOT EXISTS requests_created ON requests(created_at);
CREATE INDEX IF NOT EXISTS requests_run ON requests(run);
"""

# What a row costs: its settled cost, else (in flight, or a process that died mid-call) its worst cost.
CHARGED = "CASE WHEN status IN ('settled', 'failed', 'released') THEN COALESCE(usd, est_usd) ELSE est_usd END"


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


class SpendLedger:
    def __init__(self, directory: Path | None = None) -> None:
        self.dir = directory or home()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "spend.db"
        self.budget_path = self.dir / "budget.yaml"
        with closing(self._connect()) as db:
            db.executescript(SCHEMA)
            columns = {row[1] for row in db.execute("PRAGMA table_info(requests)")}
            if "envelope" not in columns:  # ledgers from before envelopes: their rows keep no envelope
                db.execute("ALTER TABLE requests ADD COLUMN envelope TEXT")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.execute("PRAGMA journal_mode=WAL")
        db.row_factory = sqlite3.Row
        return db

    # Budget -----------------------------------------------------------------------------------------------

    def budget(self) -> Budget:
        if not self.budget_path.exists():
            return Budget()
        raw = yaml.safe_load(self.budget_path.read_text()) or {}
        return Budget.model_validate(raw)

    def set_budget(self, budget: Budget) -> None:
        self.budget_path.write_text(yaml.safe_dump(budget.model_dump(mode="json"), sort_keys=False))
        self.budget_path.chmod(0o600)

    def status(self, *, now: datetime | None = None, db: sqlite3.Connection | None = None) -> Status:
        budget = self.budget()
        moment = now or utc_now()
        expired = budget.expires_at is not None and moment >= budget.expires_at
        since = budget.verified_at if budget.verified else None
        spent = self._charged_since(since, db)
        if budget.verified:
            assert budget.remaining_usd is not None
            reserve = 0.0 if budget.reserve_released else budget.remaining_usd * budget.reserve_fraction
            permitted = budget.remaining_usd - reserve
            reason = f"verified balance US${budget.remaining_usd:.2f} ({budget.source or 'no source given'})"
        else:
            reserve = 0.0
            permitted = budget.unverified_allowance_usd
            reason = f"no verified balance: an allowance of US${permitted:.2f} to check the remote path"
        if expired:
            reason += "; the credits have expired"
        return Status(budget.verified, permitted, spent, reserve, since, expired, reason)

    def _charged_since(self, since: datetime | None, db: sqlite3.Connection | None) -> float:
        query = f"SELECT COALESCE(SUM({CHARGED}), 0) FROM requests"
        params: tuple[Any, ...] = ()
        if since is not None:
            query += " WHERE created_at >= ?"
            params = (_iso(since),)
        if db is not None:
            return float(db.execute(query, params).fetchone()[0])
        with closing(self._connect()) as own:
            return float(own.execute(query, params).fetchone()[0])

    # Requests ---------------------------------------------------------------------------------------------

    def reserve(
        self,
        *,
        est_usd: float,
        workspace: str,
        purpose: str,
        provider: str,
        model: str,
        attempt: int,
        correlation_id: str | None = None,
    ) -> str:
        """Hold the worst cost of one call, or refuse it. Atomic across processes."""
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                status = self.status(db=db)
                if status.expired:
                    raise SpendRefused(f"refused: {status.reason}")
                if status.spent_usd + est_usd > status.permitted_usd:
                    raise SpendRefused(
                        f"refused: this call may cost up to US${est_usd:.4f} and US${status.available_usd:.4f} "
                        f"is left of US${status.permitted_usd:.2f} permitted ({status.reason}; reserve "
                        f"US${status.reserve_usd:.2f} held back)"
                    )
                envelope = self._check_envelope(est_usd, db)
                rid = new_id("spend")
                db.execute(
                    "INSERT INTO requests (id, created_at, workspace, run, purpose, correlation_id, provider, model,"
                    " attempt, status, est_usd, envelope) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'reserved', ?, ?)",
                    (
                        rid,
                        _iso(utc_now()),
                        workspace,
                        run_tag(),
                        purpose,
                        correlation_id,
                        provider,
                        model,
                        attempt,
                        est_usd,
                        envelope,
                    ),
                )
                db.execute("COMMIT")
                return rid
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def _check_envelope(self, est_usd: float, db: sqlite3.Connection) -> str | None:
        budget = self.budget()
        if not budget.envelopes:
            return None
        name = envelope_tag()
        if name not in budget.envelopes:
            raise SpendRefused(
                f"refused: spend is split into envelopes ({', '.join(sorted(budget.envelopes))}) and this call names "
                f"{'none' if name is None else repr(name)}: set UNBIDDEN_ENVELOPE"
            )
        spent = self.envelope_spent(name, db)
        cap = budget.envelopes[name]
        if spent + est_usd > cap:
            raise SpendRefused(
                f"refused: this call may cost up to US${est_usd:.4f} and envelope {name!r} has "
                f"US${max(0.0, cap - spent):.4f} left of US${cap:.2f}"
            )
        return name

    def envelope_spent(self, name: str, db: sqlite3.Connection | None = None) -> float:
        budget = self.budget()
        query = f"SELECT COALESCE(SUM({CHARGED}), 0) FROM requests WHERE envelope = ?"
        params: tuple[Any, ...] = (name,)
        if budget.envelopes_since is not None:
            query += " AND created_at >= ?"
            params = (name, _iso(budget.envelopes_since))
        if db is not None:
            return float(db.execute(query, params).fetchone()[0])
        with closing(self._connect()) as own:
            return float(own.execute(query, params).fetchone()[0])

    def settle(
        self,
        rid: str,
        *,
        usd: float | None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        usage_reported: bool,
        status: str = "settled",
        note: str | None = None,
    ) -> None:
        """`usd=None` keeps the worst cost: the call may have been billed and nothing says for how much."""
        with closing(self._connect()) as db:
            db.execute(
                "UPDATE requests SET settled_at = ?, status = ?, usd = COALESCE(?, est_usd), tokens_in = ?,"
                " tokens_out = ?, usage_reported = ?, note = ? WHERE id = ?",
                (_iso(utc_now()), status, usd, tokens_in, tokens_out, int(usage_reported), note, rid),
            )

    def release(self, rid: str, note: str) -> None:
        """Nothing was sent (the egress gate stopped it): the reservation costs nothing."""
        with closing(self._connect()) as db:
            db.execute(
                "UPDATE requests SET settled_at = ?, status = 'released', usd = 0, note = ? WHERE id = ?",
                (_iso(utc_now()), note, rid),
            )

    def rows(self, *, run: str | None = None, since: datetime | None = None) -> list[dict[str, Any]]:
        query = f"SELECT *, {CHARGED} AS charged FROM requests WHERE 1=1"
        params: list[Any] = []
        if run is not None:
            query += " AND run = ?"
            params.append(run)
        if since is not None:
            query += " AND created_at >= ?"
            params.append(_iso(since))
        with closing(self._connect()) as db:
            return [dict(r) for r in db.execute(query + " ORDER BY created_at", params)]


def summarize(rows: list[dict[str, Any]], by: str) -> dict[str, dict[str, float]]:
    """Calls, retries, failures, tokens and dollars grouped by one column (model, run, workspace, purpose)."""
    out: dict[str, dict[str, float]] = {}
    for r in rows:
        g = out.setdefault(
            str(r[by]),
            {"calls": 0, "retries": 0, "failed": 0, "tokens_in": 0, "tokens_out": 0, "usd": 0.0, "unreported": 0},
        )
        g["calls"] += 1
        g["retries"] += int(r["attempt"] > 1)
        g["failed"] += int(r["status"] == "failed")
        g["tokens_in"] += r["tokens_in"]
        g["tokens_out"] += r["tokens_out"]
        g["usd"] += float(r["charged"])
        g["unreported"] += int(r["status"] in ("settled", "failed") and not r["usage_reported"])
    return out


def worst_cost(payload_bytes: int, max_tokens: int, input_per_mtok: float, output_per_mtok: float) -> float:
    tokens_in = int(payload_bytes / BYTES_PER_TOKEN_WORST) + ENVELOPE_TOKENS
    return (tokens_in * input_per_mtok + max_tokens * output_per_mtok) / 1e6
