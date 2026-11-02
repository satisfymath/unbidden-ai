"""What belongs to the machine, not to a project: shared credentials (`~/.unbidden/.env`) and preferences
(`~/.unbidden/machine.yaml`). Projects never inherit permissions from here; only credentials and preferences."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict


def machine_dir() -> Path:
    """Where the broker reads shared credentials (`Workspace.load_env`): the user's home, not UNBIDDEN_HOME."""
    return Path.home() / ".unbidden"


def machine_env() -> Path:
    return machine_dir() / ".env"


def read_env(path: Path) -> dict[str, str]:
    """The `KEY=value` pairs of a dotenv file (comments and blanks ignored); values are returned, so callers that
    print must print names only."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text().splitlines():
        key, sep, value = line.partition("=")
        key = key.strip()
        if sep and key and not key.startswith("#"):
            values[key] = value.strip().strip("'\"")
    return values


def env_names(path: Path) -> list[str]:
    return sorted(k for k, v in read_env(path).items() if v)


def write_env(path: Path, updates: Mapping[str, str], *, remove: Iterable[str] = ()) -> None:
    """Set or replace `updates` in a dotenv file, keeping every other line as it is; written whole and atomically,
    directory 700, file 600. A value is never echoed."""
    gone = set(remove)
    lines = path.read_text().splitlines() if path.exists() else []
    out: list[str] = []
    seen: set[str] = set()
    for line in lines:
        key, sep, _ = line.partition("=")
        key = key.strip()
        if sep and key and not key.startswith("#"):
            if key in gone:
                continue
            if key in updates:
                out.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
        out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(out) + ("\n" if out else ""))
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    os.chmod(path, 0o600)


class MachinePrefs(BaseModel):
    """Preferences, never permissions."""

    model_config = ConfigDict(extra="forbid")
    dashboard: Literal["ask", "always", "never"] = "ask"
    language: str | None = None  # None: follow the terminal's locale (unbidden/i18n.py)
    language_chosen: bool = False  # True once a person chose; 0.10 wrote `language: en` without anyone choosing


def prefs_path() -> Path:
    return machine_dir() / "machine.yaml"


def load_prefs() -> MachinePrefs:
    path = prefs_path()
    if not path.exists():
        return MachinePrefs()
    raw = yaml.safe_load(path.read_text()) or {}
    if raw.get("language") == "en" and not raw.get("language_chosen"):
        raw["language"] = None  # 0.10 wrote "en" on every machine without anyone choosing it
    return MachinePrefs.model_validate(raw)


def save_prefs(prefs: MachinePrefs) -> None:
    path = prefs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(yaml.safe_dump(prefs.model_dump(), sort_keys=False))
    os.replace(tmp, path)
