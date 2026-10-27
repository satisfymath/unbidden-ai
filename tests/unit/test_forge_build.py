from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import pytest

from unbidden.contracts.llm import LLMRequest, LLMResponse
from unbidden.forge.build import Forge
from unbidden.store import Store

pytestmark = pytest.mark.unit
PATTERN = r'"(?P<method>[A-Z]+) (?P<path>/\S*) HTTP/[\d.]+" (?P<status>\d{3})'


class Brain:
    """Answers like a model would: tests as JSON, the pattern as one raw line with its backslashes."""

    async def complete(self, request: LLMRequest, identifiers: Any = None) -> LLMResponse:
        if request.purpose == "forge.tests":
            tests = []
            for row in request.messages[0].content.splitlines():
                found = re.match(r'(\d+): .*"([A-Z]+) (\S+) HTTP/1.1" (\d{3})', row)
                if found and len(tests) < 3:
                    number, method, path, status = found.groups()
                    tests.append({"line": int(number), "method": method, "path": path, "status": status})
            return LLMResponse(content=json.dumps({"tests": tests}))
        return LLMResponse(content=f"PATTERN: {PATTERN}")


def test_a_log_adapter_built_from_a_raw_pattern_passes_the_oracle(store: Store) -> None:
    statuses = ["200", "201", "404", "500", "302"]
    lines = [
        f'172.18.0.{i % 9} - - "{("GET", "POST")[i % 2]} /items/{i} HTTP/1.1" {statuses[i % 5]}' for i in range(1, 120)
    ]
    result = asyncio.run(Forge(Brain(), store).build_log_adapter("compose:api", lines))  # type: ignore[arg-type]
    assert result.adapter is not None and result.adapter.pattern == PATTERN
    assert result.adapter.status == "validated", result.adapter.quality
