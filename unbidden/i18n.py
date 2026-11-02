"""Which language Unbidden speaks to the person, and how a text table answers in it.

Resolved once per process, in this order: `UNBIDDEN_LANG`; the machine's preference (`~/.unbidden/machine.yaml`,
written by `/language` or `unbidden setup language`); the terminal's locale (`LC_ALL`, `LC_MESSAGES`, `LANG`);
English. A table module keeps `T` in English and a sibling `text_<code>.py` per language; a key missing from a
translation falls back to English, so a half-translated table never breaks a sentence. The engine's records are
not translated: what Unbidden says follows the language, what it recorded stays as recorded."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

LANGUAGES: dict[str, str] = {"en": "English", "es": "español"}
ENV = "UNBIDDEN_LANG"

_cache: dict[str, tuple[str, str]] = {}


def resolve() -> tuple[str, str]:
    """(code, source): source is `env`, `saved`, `locale` or `default`."""
    wanted = os.environ.get(ENV, "").strip().lower()
    if wanted in LANGUAGES:
        return wanted, "env"
    from unbidden.setup.machine import load_prefs

    try:
        saved = load_prefs().language
    except Exception:  # an unreadable preferences file never breaks a sentence
        saved = None
    if saved in LANGUAGES:
        return str(saved), "saved"
    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        code = os.environ.get(name, "").split(".")[0].split("_")[0].strip().lower()
        if code in LANGUAGES:
            return code, "locale"
        if code and code != "c" and code != "posix":
            break  # a locale in another language says nothing about the preference among ours
    return "en", "default"


def language() -> str:
    if "code" not in _cache:
        _cache["code"] = resolve()
    return _cache["code"][0]


def source() -> str:
    if "code" not in _cache:
        _cache["code"] = resolve()
    return _cache["code"][1]


def name(code: str | None = None) -> str:
    return LANGUAGES.get(code or language(), LANGUAGES["en"])


def set_language(code: str) -> None:
    """Save the preference on this machine and use it from now on in this process."""
    from unbidden.setup.machine import load_prefs, save_prefs

    if code not in LANGUAGES:
        raise ValueError(f"unknown language {code!r}; one of {', '.join(LANGUAGES)}")
    prefs = load_prefs()
    prefs.language = code
    prefs.language_chosen = True
    save_prefs(prefs)
    clear()


def clear() -> None:
    _cache.clear()


def lookup(english: Mapping[str, str], tables: Mapping[str, Mapping[str, str]], key: str, **kwargs: Any) -> str:
    """The sentence for `key` in the current language, English when the translation lacks it."""
    table = tables.get(language())
    text = table.get(key) if table is not None else None
    if text is None:
        text = english[key]
    return text.format(**kwargs) if kwargs else text
