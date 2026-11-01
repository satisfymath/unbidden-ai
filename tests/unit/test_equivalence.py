from __future__ import annotations

import pytest

from unbidden.lab.equivalence import sessions_differ

pytestmark = pytest.mark.unit

A, B, C = (f"{n}0000000-0000-4000-8000-000000000000" for n in "abc")
X, Y = (f"{n}0000000-0000-4000-8000-000000000000" for n in "ef")


def test_one_correspondence_holds_for_the_whole_session_across_calls() -> None:
    assert sessions_differ([{"o": A}, {"o": A}], [{"o": X}, {"o": X}]) is None
    assert "stands for" in str(sessions_differ([{"o": A}, {"o": A}], [{"o": X}, {"o": Y}]))  # one id became two


def test_two_ids_never_merge_into_one() -> None:
    assert "already stands for" in str(sessions_differ([{"o": [A, B]}], [{"o": [X, X]}]))


def test_an_id_kept_on_one_side_still_follows_the_correspondence() -> None:
    assert sessions_differ([{"o": [A, C]}], [{"o": [A, C]}]) is None
    assert sessions_differ([{"o": [A, A]}], [{"o": [A, C]}]) is not None


def test_a_value_is_never_set_aside_for_its_shape_against_another_shape() -> None:
    assert sessions_differ([{"o": A}], [{"o": "2026-10-31T05:00:00"}]) is not None
    assert sessions_differ([{"n": 1}], [{"n": "1"}]) is not None
