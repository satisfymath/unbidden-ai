"""Editing a mandate: the one place the CLI and the setup assistant change autonomy and models.

The modes, the conditions for `autonomous`, the models options and the write itself live here so that no front end
reimplements the policy. A write validates the whole mandate before the file is touched, replaces it atomically, and
records who changed what (the `MANDATE_CHANGED` event is the mandate's change log).
"""

from __future__ import annotations

import getpass
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import yaml

from unbidden.contracts.events import Event, EventType
from unbidden.contracts.guardian import Mandate
from unbidden.store import Store

MODES: dict[str, dict[str, str]] = {
    # Unbidden prepares everything and asks before anything reaches GitHub.
    "supervised": {
        "open_pull_requests": "require_approval",
        "merge_pull_requests": "deny",
        "deploy": "deny",
        "rollback": "deny",
        "use_new_capabilities": "require_approval",
    },
    # Unbidden opens pull requests on its own for what reaches the mandate's evidence level; people merge.
    "autopilot": {
        "open_pull_requests": "allow",
        "merge_pull_requests": "deny",
        "deploy": "deny",
        "rollback": "deny",
        "use_new_capabilities": "allow",
    },
    # Unbidden also merges L4 work, deploys it with the team's steps, judges every deploy, and rolls back to the
    # last healthy version when one degrades or the system goes down. Requires a passed rollback drill.
    "autonomous": {
        "open_pull_requests": "allow",
        "merge_pull_requests": "allow",
        "deploy": "allow",
        "rollback": "allow",
        "use_new_capabilities": "allow",
    },
}

# What a person chooses in plain words, and the models policy it means. Secrets and production data stay local in
# every option; the router and the egress gate decide, not this table.
MODEL_OPTIONS: dict[str, dict[str, str]] = {
    "local": {"profile": "local"},
    "mixed": {"profile": "local-first"},
    "api": {"profile": "frontier", "local_inference": "deny", "local_fallback": "deny"},
}

# The permissions a mode does not touch; each is granted on its own.
BEYOND_MODES = ("observe", "run_experiments", "provision_dependencies", "delegate_synthetic", "act_on_connections")


def read_raw(path: Path) -> dict[str, Any]:
    """The mandate file as a mapping, comments dropped (what `cmd_mode` always did)."""
    raw: object = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict) or "mandate" not in raw:
        raise ValueError(f"{path}: expected a top-level 'mandate' mapping")
    return cast(dict[str, Any], raw)


def mandate_of(raw: Mapping[str, Any]) -> dict[str, Any]:
    body: object = raw["mandate"]
    if not isinstance(body, dict):
        raise ValueError("'mandate' must be a mapping")
    return cast(dict[str, Any], body)


def _section(body: dict[str, Any], key: str, default: dict[str, Any] | None = None) -> dict[str, Any]:
    """`body[key]` as a mapping, created from `default` when absent."""
    section: object = body.setdefault(key, dict(default or {}))
    if not isinstance(section, dict):
        raise ValueError(f"'mandate.{key}' must be a mapping")
    return cast(dict[str, Any], section)


def current_mode(autonomy: Mapping[str, Any]) -> str:
    return next((m for m, v in MODES.items() if all(autonomy.get(k, "deny") == x for k, x in v.items())), "custom")


def autonomous_blockers(raw: Mapping[str, Any], store: Store) -> list[str]:
    """Why `autonomous` cannot be switched on yet: the team's deploy steps, and a rollback drill that passed."""
    body = mandate_of(raw)
    operations: dict[str, Any] = cast(dict[str, Any], body.get("operations") or {})
    drill: dict[str, Any] = cast(dict[str, Any], store.get_value("rollback_drill") or {})
    blockers: list[str] = []
    if not operations.get("deploy_steps"):
        blockers.append("autonomous needs the team's deploy steps in the mandate (operations.deploy_steps)")
    if not drill.get("passed"):
        blockers.append("autonomous needs a passed rollback drill first: run `unbidden drill`")
    return blockers


def apply_mode(raw: Mapping[str, Any], mode: str) -> dict[str, str]:
    """Set the autonomy fields a mode governs; the others keep what the mandate says."""
    autonomy = _section(mandate_of(raw), "autonomy")
    autonomy.update(MODES[mode])
    return dict(MODES[mode])


def apply_autonomy(raw: Mapping[str, Any], **fields: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Set single autonomy fields (the ones beyond a mode, e.g. act_on_connections). Returns (before, after)."""
    autonomy = _section(mandate_of(raw), "autonomy")
    before = dict(autonomy)
    for key, value in fields.items():
        if value is not None:
            autonomy[key] = value
    return before, dict(autonomy)


def apply_models(raw: Mapping[str, Any], **fields: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Set models policy fields (profile, private_code_to_frontier, local_inference, local_fallback,
    screenshots_to_frontier). Returns (before, after)."""
    models = _section(mandate_of(raw), "models", {"profile": "local-first", "private_code_to_frontier": "deny"})
    before = dict(models)
    for key, value in fields.items():
        if value is not None:
            models[key] = value
    return before, dict(models)


def apply_model_option(raw: Mapping[str, Any], option: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """One of MODEL_OPTIONS. `local` and `mixed` also lift a `deny` on local inference left by an earlier `api`."""
    fields: dict[str, str | None] = dict(MODEL_OPTIONS[option])
    if option != "api":
        fields.setdefault("local_inference", "allow")
        fields.setdefault("local_fallback", "allow")
    return apply_models(raw, **fields)


def validate(raw: Mapping[str, Any]) -> Mandate:
    return Mandate.model_validate(mandate_of(raw))


def person() -> str:
    return f"person:{getpass.getuser()}"


def write_mandate(
    path: Path, raw: Mapping[str, Any], store: Store, payload: dict[str, Any], *, actor: str | None = None
) -> Mandate:
    """Validate, then replace the file in one step, then record the change. A mandate that does not validate is
    never written, and a crash mid-write leaves the previous file in place."""
    mandate = validate(raw)
    text = yaml.safe_dump(dict(raw), sort_keys=False)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)
    store.append_event(Event(type=EventType.MANDATE_CHANGED, actor=actor or person(), payload=payload))
    return mandate
