from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from unbidden.research.robustness import parse_crashes, public_functions

pytestmark = pytest.mark.unit

OUTPUT = """
___________________________ test_wrap_never_crashes ___________________________

    @given(st.text())
>   def test_wrap_never_crashes(s):

tests/test_unbidden_robustness.py:9:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
rich/text.py:1200: in wrap
    lines = self.divide(offsets)
rich/_wrap.py:42: in divide_line
    word = words[index]
E   IndexError: list index out of range
Falsifying example: test_wrap_never_crashes(
    s='\\u200d\\u200d',
)

___________________________ test_escape_round_trips ___________________________
rich/markup.py:50: in escape
    return x
E   AssertionError: assert 'a\\\\' == 'a\\\\\\\\'

____________________________ test_parse_never_crashes ____________________________
rich/markup.py:80: in render
E   rich.errors.MarkupError: closing tag '[/]' has nothing to close
"""


def test_only_crashes_inside_the_package_with_bug_types_count() -> None:
    (crash,) = parse_crashes(OUTPUT, "rich")
    assert crash.test == "test_wrap_never_crashes"
    assert crash.exception == "IndexError" and crash.frame == "rich/_wrap.py:42 in divide_line"
    assert "\\u200d" in crash.example


def test_the_regression_test_keeps_imports_and_one_test() -> None:
    from unbidden.lab.robust import single_test

    source = "from rich.text import Text\n\ndef test_a(s):\n    Text(s)\n\ndef test_b(s):\n    pass\n"
    reduced = single_test(source, "test_a")
    assert "from rich.text import Text" in reduced and "def test_a" in reduced and "test_b" not in reduced
    unused = "from rich.cells import cell_len\nfrom rich.text import Text\n\ndef test_a(s):\n    Text(s)\n"
    assert "cell_len" not in single_test(unused, "test_a")


GROUP = """
_________________________ test_split_text_never_crashes _________________________
  | ExceptionGroup: Hypothesis found 2 distinct failures. (2 sub-exceptions)
  +-+---------------- 1 ----------------
    | Traceback (most recent call last):
    |   File "/work/tests/test_unbidden_robustness.py", line 69, in test_split_text_never_crashes
    |   File "/work/rich/cells.py", line 266, in _split_text
    | IndexError: list index out of range
    | Failing test case: test_split_text_never_crashes(
    |     text='0\\x1f',
    | )
    |
    +---------------- 2 ----------------
    |   File "/work/rich/cells.py", line 256, in _split_text
    | ZeroDivisionError: division by zero
    | Failing test case: test_split_text_never_crashes(
    |     text='\\x1f',
    | )
    |
"""


def test_every_failure_of_an_exception_group_is_read() -> None:
    crashes = parse_crashes(GROUP, "rich")
    assert [(c.exception, c.frame) for c in crashes] == [
        ("IndexError", "rich/cells.py:266 in _split_text"),
        ("ZeroDivisionError", "rich/cells.py:256 in _split_text"),
    ]


def _commit(repo: Path, files: dict[str, str]) -> str:
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for path, text in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "c"], check=True
    )
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def test_probe_targets_are_the_packages_users_import(tmp_path: Path) -> None:
    from unbidden.observe.stack import PythonStack
    from unbidden.research.robustness import probe_targets

    rev = _commit(
        tmp_path,
        {
            "src/textkit/__init__.py": "",
            "src/textkit/wrap.py": "def wrap(text: str, width: int) -> str:\n    return text\n\n"
            "def fill(text: str) -> str:\n    return text\n",
            "src/helpers/__init__.py": "",
            "src/helpers/one.py": "def one(n: int) -> int:\n    return n\n",
            "tests/__init__.py": "",
            "tests/test_wrap.py": "def test_wrap(): pass\n",
            "src/empty/__init__.py": "",
        },
    )
    stack = PythonStack(
        version="3.12", lockfile=None, manifest="pyproject.toml", ruff=False, pyright=False, pytest=True
    )
    targets = probe_targets(tmp_path, rev, stack)
    assert targets == [("src/textkit", 2), ("src/helpers", 1)]
    # Imported by its own name, not through the source root.
    assert public_functions(tmp_path, rev, "src/textkit")[0].startswith("from textkit.wrap import wrap")


# pytest 9 and Hypothesis 6.17x: frames without `in function`, "Failing test case", and a summary that names an
# ExceptionGroup from another test right after the last failure.
NEW_FORMAT = """
_______________________ test_delta_never_crashes ________________________

value = 0, unit = ''

    def test_delta_never_crashes(value, unit):
>       delta(value, unit=unit)

tests/test_unbidden_robustness.py:79:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

    def delta(value, unit="seconds"):
        units = {"seconds": 1}
>       return units[unit] * value
E       KeyError: ''
E       Failing test case: test_delta_never_crashes(
E           value=0,
E           unit='',
E       )

src/textkit/time.py:142: KeyError
=========================== short test summary info ============================
FAILED tests/test_unbidden_robustness.py::test_size - ExceptionGroup: Hypothesis found 3 distinct failures.
FAILED tests/test_unbidden_robustness.py::test_delta_never_crashes - KeyError: ''
"""


def test_crashes_in_the_newer_pytest_and_hypothesis_formats() -> None:
    (crash,) = parse_crashes(NEW_FORMAT.replace("src/textkit/time.py:142: KeyError", "src/textkit/time.py:142: "),
                             "src/textkit")  # fmt: skip
    assert crash.exception == "KeyError"
    assert crash.frame == "src/textkit/time.py:142 in delta"
    assert crash.example.startswith("test_delta_never_crashes(\nvalue=0,")
