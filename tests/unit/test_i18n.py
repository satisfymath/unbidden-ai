"""The language Unbidden speaks: resolved from UNBIDDEN_LANG, the saved preference, the locale, English; every
translation table carries the same keys and placeholders as its English table; a 0.10 preferences file that says
`en` means nothing was chosen."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from unbidden import i18n
from unbidden.setup import machine
from unbidden.setup import text as setup_text
from unbidden.setup import text_es as setup_es
from unbidden.tui import text as tui_text
from unbidden.tui import text_es as tui_es
from unbidden.web import text as web_text
from unbidden.web import text_es as web_es

pytestmark = pytest.mark.unit

PLACEHOLDER = re.compile(r"{(\w+)(?::[^}]*)?}")


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("HOME", str(tmp_path))
    for name in ("UNBIDDEN_LANG", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(name, raising=False)
    i18n.clear()
    yield tmp_path
    i18n.clear()


@pytest.mark.parametrize(
    ("english", "spanish", "name"),
    [(setup_text.T, setup_es.T, "setup"), (tui_text.T, tui_es.T, "tui"), (web_text.T, web_es.T, "web")],
)
def test_every_translation_has_the_same_keys_and_placeholders(english: dict, spanish: dict, name: str) -> None:
    assert set(spanish) == set(english), name
    for key, text in english.items():
        assert set(PLACEHOLDER.findall(spanish[key])) == set(PLACEHOLDER.findall(text)), (name, key)


def test_english_by_default_then_the_locale_then_the_saved_choice_then_the_environment(monkeypatch) -> None:
    assert i18n.resolve() == ("en", "default")
    monkeypatch.setenv("LANG", "es_CL.UTF-8")
    i18n.clear()
    assert i18n.resolve() == ("es", "locale") and i18n.language() == "es" and i18n.name() == "español"
    monkeypatch.setenv("LANG", "fr_FR.UTF-8")  # a language we do not have says nothing
    i18n.clear()
    assert i18n.resolve() == ("en", "default")
    i18n.set_language("es")
    assert machine.load_prefs().language == "es" and i18n.resolve() == ("es", "saved")
    monkeypatch.setenv("LANG", "es_CL.UTF-8")
    i18n.set_language("en")  # English chosen on a Spanish terminal is a choice, unlike the file 0.10 wrote
    assert i18n.resolve() == ("en", "saved")
    monkeypatch.setenv("UNBIDDEN_LANG", "en")
    i18n.clear()
    assert i18n.resolve() == ("en", "env")
    with pytest.raises(ValueError):
        i18n.set_language("klingon")


def test_a_0_10_preferences_file_with_en_means_nothing_was_chosen(monkeypatch) -> None:
    machine.prefs_path().parent.mkdir(parents=True)
    machine.prefs_path().write_text("dashboard: ask\nlanguage: en\n")
    assert machine.load_prefs().language is None
    monkeypatch.setenv("LANG", "es_ES.UTF-8")
    i18n.clear()
    assert i18n.language() == "es"


def test_the_tables_answer_in_the_language_and_fall_back_to_english(monkeypatch) -> None:
    assert tui_text.t("setup.yes") == "Yes" and setup_text.t("found.title") == "Found"
    monkeypatch.setenv("UNBIDDEN_LANG", "es")
    i18n.clear()
    assert tui_text.t("setup.yes") == "Sí" and setup_text.t("found.title") == "Encontrado"
    assert web_text.t("status.jobs", jobs="x") == "Jobs: x"
    monkeypatch.delitem(tui_es.T, "setup.yes")
    assert tui_text.t("setup.yes") == "Yes"  # a key the translation lacks: English, never a crash
