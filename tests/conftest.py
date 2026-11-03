from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from unbidden.contracts.guardian import (
    Autonomy,
    AutonomyPolicy,
    EgressPolicy,
    GitHubPolicy,
    Mandate,
    RemoteModelPolicy,
)
from unbidden.guardian.credentials import CredentialBroker, reset
from unbidden.store import Store


@pytest.fixture(autouse=True)
def credentials() -> CredentialBroker:
    """A fresh broker per test, with the grants a runtime would give the test names."""
    held = reset()
    for name, purpose in (("GITHUB_TOKEN", "github"), ("TEST_KEY", "model.remote"), ("MODEL_API_KEY", "model.remote")):
        held.grant(name, purpose)
    return held


@pytest.fixture(autouse=True)
def spend_home(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Every test gets its own machine-wide spend ledger, never the real one in ~/.unbidden."""
    home = tmp_path_factory.mktemp("unbidden-home")
    monkeypatch.setenv("UNBIDDEN_HOME", str(home))
    monkeypatch.delenv("UNBIDDEN_RUN", raising=False)
    return home


@pytest.fixture(autouse=True)
def english(monkeypatch: pytest.MonkeyPatch) -> None:
    """The suite reads English whatever the developer's locale; the language tests and the web tests set theirs."""
    from unbidden import i18n

    monkeypatch.setenv("UNBIDDEN_LANG", "en")
    i18n.clear()


@pytest.fixture(autouse=True)
def no_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test runs a command in the developer's terminal (gh install, gh auth login); a test passes its own."""
    from unbidden.setup import wizard

    def refuse(argv: list[str]) -> int:
        raise RuntimeError(f"a test reached the terminal: {' '.join(argv)}")

    monkeypatch.setattr(wizard, "run_in_terminal", refuse)


@pytest.fixture(autouse=True)
def no_model_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test proves a key against Meta's API or installs Ollama on the developer's machine: the key probe answers
    as an accepted key, the Ollama installer is absent. A test of those paths passes or patches its own."""
    from unbidden.setup import ollama_install, wizard

    def accepted(ws: Any, **kwargs: Any) -> dict[str, Any]:
        return {"ok": True, "model": "muse-spark-1.3", "usd": 0.0001, "answer": "OK"}

    monkeypatch.setattr(wizard, "probe_remote", accepted)
    monkeypatch.setattr(ollama_install, "install_command", lambda: None)
    monkeypatch.setattr(ollama_install, "start_server", lambda url, wait_s=0.0: False)


@pytest.fixture(autouse=True)
def no_gh_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests never pick up the developer's real `gh` sign-in; a test of that path fakes `gh` itself."""
    from unbidden.setup import github_access

    monkeypatch.setenv(github_access.OPT_OUT, "off")
    github_access.forget_gh_token()


@pytest.fixture(autouse=True)
def no_ci_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests never ask GitHub about a commit or a repository; a test that needs an answer sets its own."""
    import unbidden.observe.ci as ci

    monkeypatch.setattr(ci, "fetch_runs", lambda *a, **k: ([], None))  # pyright: ignore[reportUnknownLambdaType]
    monkeypatch.setattr(ci, "fork_parent", lambda *a, **k: None)  # pyright: ignore[reportUnknownLambdaType]


@pytest.fixture
def store() -> Store:
    return Store(None)


@pytest.fixture
def mandate() -> Mandate:
    return Mandate(
        workspace="shop",
        autonomy=AutonomyPolicy(
            observe=Autonomy.ALLOW,
            run_experiments=Autonomy.ALLOW,
            provision_dependencies=Autonomy.ALLOW,
            delegate_synthetic=Autonomy.ALLOW,
            open_pull_requests=Autonomy.REQUIRE_APPROVAL,
        ),
        egress=EgressPolicy(
            package_registries=["registry.npmjs.org", "pypi.org"],
            remote_models=RemoteModelPolicy(destinations=["api.meta.ai"]),
            github=GitHubPolicy(repository="acme/shop"),
        ),
    )


# A stand-in for the background agent: a child process that takes the engine lock as `unbidden watch` would, ends
# cleanly on SIGTERM, and whose command line names unbidden (owner.alive_holder looks for that). With a second
# argument "exit-dirty" it leaves without releasing when its stdin closes, like a crash would.
STANDIN_AGENT = """
import signal, sys, time
from pathlib import Path
from unbidden.daemon.owner import EngineLock
lock = EngineLock.acquire(Path(sys.argv[1]), "watch")
def bye(*_):
    lock.release()
    sys.exit(0)
signal.signal(signal.SIGTERM, bye)
print("held", flush=True)
if len(sys.argv) > 2 and sys.argv[2] == "exit-dirty":
    sys.stdin.readline()
    sys.exit(0)
time.sleep(120)
"""


@pytest.fixture
def standin_argv():  # type: ignore[no-untyped-def]
    """argv for the stand-in agent over a state directory: `standin_argv(state_dir, *modes)`."""
    import sys

    def argv(state_dir: Path, *modes: str) -> list[str]:
        return [sys.executable, "-c", STANDIN_AGENT, str(state_dir), *modes]

    return argv


@pytest.fixture
def reaper():  # type: ignore[no-untyped-def]
    """Child processes a test starts; whatever happens, none outlives the test."""
    import contextlib
    import os
    import signal

    pids: list[int] = []
    yield pids
    for pid in pids:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
        with contextlib.suppress(ChildProcessError, OSError):
            os.waitpid(pid, 0)
