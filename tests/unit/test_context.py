from __future__ import annotations

from pathlib import Path

import pytest

from unbidden.brain.codeblocks import parse_files
from unbidden.lab.context import SpliceError, payload_bytes, render, select, splice

pytestmark = pytest.mark.unit


def big_module(tmp_path: Path) -> Path:
    body = ["import os", "from typing import Any", ""]
    for i in range(400):
        body += [f"def f{i}(x: int) -> int:", f'    """Function {i}."""', f"    return x + {i}", ""]
    (tmp_path / "m.py").write_text("\n".join(body) + "\n")
    return tmp_path


def test_small_files_are_sent_whole(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")
    selection = select(tmp_path, [("a.py", 1)], budget=1000)
    assert selection.mode == "files" and selection.files == {"a.py": "x = 1\n"}


def test_a_large_file_is_excerpted_around_each_finding_with_its_imports(tmp_path: Path) -> None:
    base = big_module(tmp_path)
    line = 3 + 4 * 200 + 3  # inside f200
    selection = select(base, [("m.py", line)], budget=4000)
    assert selection.mode == "excerpts" and selection.bytes <= 4000
    keys = [e.key for e in selection.excerpts]
    assert keys == ["m.py:1-2", f"m.py:{line - 2}-{line}"]  # the import header, then f200 whole
    assert selection.excerpts[1].text.startswith("def f200(")


def test_selection_is_deterministic_and_measured_in_payload_bytes(tmp_path: Path) -> None:
    base = big_module(tmp_path)
    findings = [("m.py", 900), ("m.py", 20), ("m.py", 905)]
    assert select(base, findings, 6000) == select(base, list(reversed(findings)), 6000)
    assert payload_bytes('a"\n') == 5  # quote and newline are escaped in the JSON the gate measures


def test_findings_that_cannot_all_be_shown_send_nothing(tmp_path: Path) -> None:
    base = big_module(tmp_path)
    selection = select(base, [("m.py", n) for n in range(10, 1600, 40)], budget=600)
    assert selection.mode == "does_not_fit" and selection.excerpts == []
    assert "nothing partial is sent" in selection.reason


def test_answers_replace_exactly_the_excerpts_shown(tmp_path: Path) -> None:
    base = big_module(tmp_path)
    selection = select(base, [("m.py", 806)], budget=4000)
    shown = render(selection, "#")
    assert "# file: m.py:804-806" in shown
    answer = parse_files("```\n# file: m.py:804-806\ndef f200(x: int) -> int:\n    return x + 200\n```\n")
    files = splice(base, selection.excerpts, answer)
    lines = files["m.py"].splitlines()
    assert lines[803:805] == ["def f200(x: int) -> int:", "    return x + 200"]
    assert lines[805] == "" and lines[806] == "def f201(x: int) -> int:"  # the rest is untouched
    with pytest.raises(SpliceError, match="not shown"):
        splice(base, selection.excerpts, {"m.py:1-900": "x\n"})
