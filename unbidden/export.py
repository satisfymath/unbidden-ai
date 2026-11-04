"""`unbidden export`: a workspace's evidence as plain files a campaign repository can publish.

What is written is what the store holds (already redacted on its way in), redacted once more on its way out, then
scanned by the guardian's secret scanner file by file. A bundle in which the scanner still finds anything is deleted
whole and the export fails, naming the file and the rule, never the value. Nothing but records is read: no `.env`,
no credential, no UI settings, no database file is ever copied.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from unbidden import __version__
from unbidden.brain.spend import SpendLedger
from unbidden.contracts.guardian import Mandate
from unbidden.guardian.scanner import redact_json, scan, secret_hits
from unbidden.store import Store

# Collections of the workspace's store that are evidence: what was found, tried, proposed, decided, deployed and
# asked, and every model call and payload that left. Others (the world model, connections, capabilities) describe
# the environment, not the work, and are left out.
COLLECTIONS = (
    "opportunities",
    "hypotheses",
    "experiment_specs",
    "experiments",
    "proposals",
    "decisions",
    "deploy_verdicts",
    "deployments",
    "holds",
    "approvals",
    "acceptances",
    "actions",
    "goal_runs",
    "model_runs",
    "transcripts",
    "egress",
    "needs",
    "asks",
    "blocks",
)
# The deploy ledger lives in the store's key-value table (operate/ledger.py, operate/deploy.py).
DEPLOY_KEYS = (
    "unbidden_deploys",
    "container_deploys",
    "deploy_sequence",
    "deployed_by_unbidden",
    "rollback_drill",
    "image_bindings",
)
MANIFEST = "manifest.json"


class ExportRefused(RuntimeError):
    """The scanner found a secret in a written file; the bundle was deleted."""

    def __init__(self, file: str, rule: str) -> None:
        super().__init__(f"{file} holds what looks like a secret ({rule}); the bundle was deleted, nothing exported")
        self.file = file
        self.rule = rule


@dataclass(frozen=True)
class Written:
    name: str
    lines: int
    bytes: int
    sha256: str

    def entry(self) -> dict[str, Any]:
        return {"name": self.name, "lines": self.lines, "bytes": self.bytes, "sha256": self.sha256}


def default_out(state_dir: Path, now: datetime | None = None) -> Path:
    return state_dir / "export" / (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")


def _write(out: Path, name: str, records: Iterable[Any], *, jsonl: bool = True) -> Written:
    path = out / name
    if jsonl:
        lines = [json.dumps(redact_json(r), sort_keys=True, ensure_ascii=False, default=str) for r in records]
        text = "".join(line + "\n" for line in lines)
        count = len(lines)
    else:
        (record,) = records
        text = json.dumps(redact_json(record), sort_keys=True, ensure_ascii=False, indent=2, default=str) + "\n"
        count = text.count("\n")
    data = text.encode()
    path.write_bytes(data)
    return Written(name, count, len(data), hashlib.sha256(data).hexdigest())


def _strings(value: Any) -> Iterable[str]:
    """Every string of a JSON value, keys included: what the scanner judges, one by one, as the store redacts."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():  # pyright: ignore[reportUnknownVariableType]
            yield str(k)  # pyright: ignore[reportUnknownArgumentType]
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:  # pyright: ignore[reportUnknownVariableType]
            yield from _strings(v)


def find_secret(path: Path) -> str | None:
    """The rule of the first secret the scanner finds in a written file, or None."""
    text = path.read_text(encoding="utf-8")
    try:
        if path.suffix == ".json":
            docs: list[Any] = [json.loads(text)]
        else:
            docs = [json.loads(line) for line in text.splitlines() if line.strip()]
    except json.JSONDecodeError:
        docs = [text]
    for doc in docs:
        for s in _strings(doc):
            hits = secret_hits(scan(s))
            if hits:
                return hits[0].kind
    return None


def export_bundle(
    store: Store, mandate: Mandate, out: Path, *, ledger: SpendLedger | None = None, now: datetime | None = None
) -> dict[str, Any]:
    """Write the bundle into `out` (new, or empty) and return its manifest. Raises ExportRefused, with the bundle
    deleted, when the scanner finds a secret in any written file."""
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"{out} is not empty; export into a new directory")
    out.mkdir(parents=True, exist_ok=True)
    try:
        written = [
            _write(out, "events.jsonl", store.event_rows()),
            _write(out, "audit.jsonl", store.audit_rows()),
            *(_write(out, f"{c}.jsonl", store.documents(c)) for c in COLLECTIONS),
            _write(
                out,
                "deploy_ledger.jsonl",
                ({"key": k, "value": v} for k in DEPLOY_KEYS if (v := store.get_value(k)) is not None),
            ),
            _write(out, "spend.jsonl", (ledger or SpendLedger()).rows(workspace=mandate.workspace)),
            _write(out, "mandate.json", [mandate.model_dump(mode="json")], jsonl=False),
        ]
        manifest = {
            "unbidden_version": __version__,
            "workspace": mandate.workspace,
            "created_at": (now or datetime.now(UTC)).isoformat(),
            "files": [w.entry() for w in written],
        }
        (out / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        for name in [*(w.name for w in written), MANIFEST]:
            rule = find_secret(out / name)
            if rule is not None:
                raise ExportRefused(name, rule)
    except BaseException:
        shutil.rmtree(out, ignore_errors=True)
        raise
    return manifest
