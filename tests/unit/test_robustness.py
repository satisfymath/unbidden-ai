from __future__ import annotations

import pytest

from unbidden.research.robustness import parse_crashes

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
