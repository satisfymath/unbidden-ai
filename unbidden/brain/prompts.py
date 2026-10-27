"""Prompts live in files next to this module, so a change to one is a reviewable diff with its own hash."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

_DIR = Path(__file__).parent / "prompts"
_VAR = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}")


@dataclass(frozen=True, slots=True)
class Prompt:
    name: str
    template: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.template.encode()).hexdigest()

    @property
    def variables(self) -> set[str]:
        return set(_VAR.findall(self.template))

    def render(self, **values: str) -> str:
        missing = self.variables - values.keys()
        if missing:
            raise KeyError(f"prompt {self.name} needs {sorted(missing)}")
        return _VAR.sub(lambda m: values[m.group(1)], self.template)


@cache
def load_prompt(name: str) -> Prompt:
    return Prompt(name, (_DIR / f"{name}.md").read_text())
