"""A sandbox Postgres whose password lives in an untracked .env (resolved empty) still starts: it trusts its
clients on its internal network (seen on the ihatemoney demo: every measurement waited 90 s and failed)."""

from __future__ import annotations

from typing import Any

import pytest

from unbidden.observe.compose import Service
from unbidden.sandbox import sidecars

pytestmark = pytest.mark.unit


def _service(env: dict[str, str]) -> Service:
    return Service(name="db", image="postgres:17-alpine", build_context=None, dockerfile=None, environment=env,
                   depends_on=(), ports=())  # fmt: skip


@pytest.mark.parametrize(
    ("env", "trusted"),
    [
        ({"POSTGRES_USER": "u", "POSTGRES_PASSWORD": ""}, True),
        ({"POSTGRES_USER": "u"}, True),
        ({"POSTGRES_USER": "u", "POSTGRES_PASSWORD": "secret"}, False),
        ({"POSTGRES_PASSWORD": "", "POSTGRES_HOST_AUTH_METHOD": "md5"}, False),
    ],
)
def test_an_empty_password_starts_a_trusting_throwaway_database(
    env: dict[str, str], trusted: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, ...]] = []

    class Done:
        returncode, stdout, stderr = 0, "", ""

    def run(docker: str, *argv: str, **_: Any) -> Done:
        calls.append(argv)
        return Done()

    monkeypatch.setattr(sidecars, "_run", run)
    with sidecars.data_services([_service(env)]):
        pass
    started = next(c for c in calls if c[0] == "run")
    assert ("POSTGRES_HOST_AUTH_METHOD=trust" in started) is trusted
