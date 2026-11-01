"""The credential broker: secrets live here, outside the process environment, and are handed out per use.

Before, `.unbidden/.env` was copied into `os.environ`, where any code in the process could read it, including code
that builds prompts and every subprocess (a sandbox's setup, a team's deploy step) that inherits the environment.
Now:
- secrets from Unbidden's own `.env` files, and the declared ones already in the environment, are moved here and
  removed from `os.environ`;
- each secret is handed out only for the purposes it was granted (the remote model's key for `model.remote`, the
  GitHub token for `github`, the probe user for `probe`); every hand-out and every refusal is recorded, never the
  value;
- the values themselves are known to the egress gate, which refuses any payload that contains one.

This is not a vault: the values are still in this process's memory. What it changes is who can reach them.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

MIN_SECRET_LENGTH = 8  # shorter values (a port, "true") would match ordinary text


@dataclass
class CredentialBroker:
    _values: dict[str, str] = field(default_factory=dict[str, str])
    _grants: dict[str, set[str]] = field(default_factory=dict[str, set[str]])
    audit: Callable[[str, str, bool], None] | None = None  # (name, purpose, given): the value is never passed

    def load(self, paths: Iterable[Path]) -> None:
        """Read `KEY=value` files; a value already held is kept (the first file wins, as before)."""
        for path in paths:
            if not path.exists():
                continue
            for line in path.read_text().splitlines():
                key, sep, value = line.partition("=")
                key = key.strip()
                if sep and key and not key.startswith("#"):
                    self._values.setdefault(key, value.strip().strip("'\""))
                    os.environ.pop(key, None)

    def grant(self, name: str, purpose: str) -> None:
        """Declare that `name` may be used for `purpose`. A value set in the environment is taken from it."""
        self._grants.setdefault(name, set()).add(purpose)
        if name in os.environ and name not in self._values:
            self._values[name] = os.environ.pop(name)
        else:
            os.environ.pop(name, None)

    def _absorb(self, name: str) -> None:
        """A granted secret exported in the environment after the grant is taken from it on first use."""
        if name in self._grants and name not in self._values and name in os.environ:
            self._values[name] = os.environ.pop(name)

    def has(self, name: str) -> bool:
        self._absorb(name)
        return bool(self._values.get(name))

    def get(self, name: str, purpose: str) -> str | None:
        self._absorb(name)
        given = purpose in self._grants.get(name, set()) and name in self._values
        if self.audit is not None:
            self.audit(name, purpose, given)
        return self._values[name] if given else None

    def secrets(self) -> list[str]:
        return [v for v in self._values.values() if len(v) >= MIN_SECRET_LENGTH]

    def leaked(self, payload: str) -> list[str]:
        """Names of held secrets whose value appears in `payload`."""
        return sorted(
            name for name, value in self._values.items() if len(value) >= MIN_SECRET_LENGTH and value in payload
        )


_broker = CredentialBroker()


def broker() -> CredentialBroker:
    """The process's one broker."""
    return _broker


def reset(fresh: CredentialBroker | None = None) -> CredentialBroker:
    """Replace the process's broker (tests)."""
    global _broker
    _broker = fresh or CredentialBroker()
    return _broker
