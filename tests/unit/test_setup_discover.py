"""What setup finds on its own: the remote, the scope, the compose services and external URLs, the machine, the
key, the option those facts amount to. Reads only."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from unbidden.guardian.credentials import broker, reset
from unbidden.setup import machine
from unbidden.setup.discover import discover
from unbidden.workspace import Workspace

pytestmark = pytest.mark.unit


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    import unbidden.runtime as runtime
    from unbidden.brain import hardware

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for name in ("MODEL_API_KEY", "GITHUB_TOKEN", "GH_TOKEN"):  # never the developer's own
        monkeypatch.delenv(name, raising=False)
    reset()
    monkeypatch.setattr(runtime, "installed_models", lambda url: set())
    from unbidden.setup import discover as discover_

    monkeypatch.setattr(discover_, "_ollama_installed", lambda: False)
    monkeypatch.setattr(
        hardware, "detect", lambda: hardware.Machine(total_gb=16.0, apple_silicon=True, chip="test", gpu_gb=0.0)
    )
    repo = tmp_path / "shop"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", "git@github-work:acme/shop.git"], check=True)
    monkeypatch.chdir(repo)
    return repo


def _commit(repo: Path, message: str = "c") -> None:
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            message,
        ],
        check=True,
    )


def test_an_empty_repository_is_found_without_a_commit(repo: Path) -> None:
    found = discover(Workspace(repo))
    assert found.slug == "acme/shop" and found.head is None and found.scope == []
    assert found.compose_path is None and found.services == [] and found.external == []
    assert found.option() == ("local", "models.why.none")
    assert found.github.source is None and not found.key_present
    data = found.as_dict()
    assert data["repository"] == "acme/shop" and data["option"] == "local" and data["github"] is None
    assert data["option_why"] == "no key and no local model yet"


def test_compose_services_and_external_urls_are_read_at_head(repo: Path) -> None:
    (repo / "compose.yaml").write_text(
        "services:\n  db:\n    image: postgres:16\n  cache:\n    image: redis:7\n  app:\n    image: shop\n"
        "    environment:\n      DATABASE_URL: postgres://u:p@db:5432/shop\n"
        "      ANALYTICS: postgres://r@analytics.internal:5433/stats\n      BILLING_URL: https://billing.example.com/v1\n"
    )
    _commit(repo)
    (repo / "compose.yaml").write_text("services: {}\n")  # uncommitted: not what is read
    found = discover(Workspace(repo))
    assert found.head is not None and found.compose_path == "compose.yaml"
    assert found.services == [("db", "postgres"), ("cache", "redis"), ("app", None)]
    assert [(k, loc) for k, loc, _ in found.external] == [
        ("postgres", "analytics.internal:5433/stats"),
        ("http_api", "https://billing.example.com:443"),
    ]
    assert found.external[0][2] == "compose.yaml service app ANALYTICS"


def test_a_saved_key_and_a_local_model_make_the_mixed_option(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import unbidden.runtime as runtime
    from unbidden.brain import hardware

    machine.write_env(machine.machine_env(), {"MODEL_API_KEY": "k-0123456789"})
    tag = hardware.recommend(hardware.detect(), set()).model.tag
    monkeypatch.setattr(runtime, "installed_models", lambda url: {tag})
    found = discover(Workspace(repo))
    assert found.key_present and found.local_model and found.ollama_present
    assert found.option() == ("mixed", "models.why.mixed")
    assert broker().has("MODEL_API_KEY")  # loaded, never shown

    monkeypatch.setattr(runtime, "installed_models", lambda url: set())
    assert discover(Workspace(repo)).option()[0] == "api"
