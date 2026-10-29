"""`unbidden doctor` tells a refused key from an unreachable API (stage 7: a 401 on the model listing was reported as
"not reachable", while calls with the same key worked)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from unbidden.cli import meta_api_status

pytestmark = pytest.mark.unit


def answering(status: int) -> Any:
    return lambda *a, **k: httpx.Response(status)


def test_each_cause_is_said_as_it_is() -> None:
    assert meta_api_status(False) == (False, "no MODEL_API_KEY: frontier models are off")
    assert meta_api_status(True, answering(200)) == (True, "key set, API reachable")
    ok, why = meta_api_status(True, answering(401))
    assert not ok and "listing refuses the key (401)" in why and "replace" not in why

    def down(*a: Any, **k: Any) -> Any:
        raise httpx.ConnectError("no route")

    assert meta_api_status(True, down) == (False, "key set, API not reachable (ConnectError)")
