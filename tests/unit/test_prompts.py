from __future__ import annotations

import pytest

from unbidden.brain.prompts import Prompt

pytestmark = pytest.mark.unit


def test_render_and_missing_variables() -> None:
    prompt = Prompt("t", "Fix {{ rule }} in {{path}}.")
    assert prompt.variables == {"rule", "path"}
    assert prompt.render(rule="TS2322", path="a.ts") == "Fix TS2322 in a.ts."
    with pytest.raises(KeyError):
        prompt.render(rule="x")
    assert len(prompt.sha256) == 64
