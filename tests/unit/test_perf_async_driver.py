"""The measurement driver for an asynchronous suite (stage 8 regression on Conduit, B-6: every workload failed on
event loops; a synchronous driver test cannot use the suite's async fixtures). Run here for real with pytest-asyncio
on a synthetic suite, with LAB_DIR pointed at a temporary directory."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from unbidden.lab import perf
from unbidden.lab.perf import async_driver, async_suite

pytestmark = pytest.mark.unit

CONFTEST = """import pytest_asyncio

@pytest_asyncio.fixture
async def client():
    class Client:
        async def get(self, path):
            return 200
    yield Client()
"""
WORKLOAD = """async def build(client):
    seeded = [1, 2, 3]
    async def call():
        return await client.get("/items")
    return call
"""


def test_an_async_suite_is_recognized_and_its_driver_awaits_the_fixtures_build_and_call(tmp_path: Path) -> None:
    files = {
        "pyproject.toml": '[project]\nname = "x"\ndependencies = ["pytest-asyncio"]\n',
        "tests/conftest.py": CONFTEST,
    }
    assert async_suite(lambda p: files[p], list(files)) == "asyncio"
    assert async_suite(lambda p: "def plain(): ...\n", ["tests/conftest.py"]) is None
    driver = async_driver(WORKLOAD, "asyncio")
    assert driver is not None and "async def test_unbidden_workload(client):" in driver
    lab = tmp_path / "lab"
    lab.mkdir()
    (lab / "workload.py").write_text(WORKLOAD)
    (tmp_path / "conftest.py").write_text(CONFTEST)
    (tmp_path / "test_driver.py").write_text(driver.replace("/work/" + perf.LAB_DIR, str(lab)))
    ran = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(tmp_path)],
                         capture_output=True, text=True, cwd=tmp_path)  # fmt: skip
    assert ran.returncode == 0, ran.stdout[-2000:]
    result = json.loads((lab / "result.json").read_text())
    assert len(result["latencies_ms"]) == perf.SAMPLES
