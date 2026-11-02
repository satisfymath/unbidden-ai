"""Every sentence of the app formats, and every key in the table is used somewhere in the app."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from unbidden.tui import text

pytestmark = pytest.mark.unit

PLACEHOLDER = re.compile(r"{(\w+)(?::[^}]*)?}")


@pytest.mark.parametrize("key", sorted(text.T))
def test_every_entry_formats_with_its_named_placeholders(key: str) -> None:
    names = set(PLACEHOLDER.findall(text.T[key]))
    values: dict[str, object] = {}
    for name in names:
        spec = re.search("{" + name + r":([^}]*)}", text.T[key])
        values[name] = 1.5 if spec and ("f" in spec.group(1) or "g" in spec.group(1)) else "x"
    out = text.t(key, **values)
    assert "{" not in out and "}" not in out


def test_no_entry_is_unreferenced() -> None:
    package = Path(text.__file__).parent
    code = "\n".join(p.read_text() for p in package.glob("*.py") if p.name != "text.py")
    unreferenced = [
        k for k in text.T if f'"{k}"' not in code and f"'{k}'" not in code and not _built_dynamically(k, code)
    ]
    assert unreferenced == [], unreferenced


def _built_dynamically(key: str, code: str) -> bool:
    """A key chosen at run time (`"open.highlight.ask" if asks else "open.highlight"`) is still referenced."""
    stem = key.rsplit(".", 1)[0]
    return f'"{stem}' in code and any(f'"{key}"' in line or f"'{key}'" in line for line in code.splitlines())


def test_the_voice_has_no_exclamation_marks_or_emoji() -> None:
    for key, sentence in text.T.items():
        assert "!" not in sentence.replace("!!", ""), key
        assert all(ord(ch) < 0x1F000 for ch in sentence), key
