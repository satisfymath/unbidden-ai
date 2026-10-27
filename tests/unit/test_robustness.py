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
