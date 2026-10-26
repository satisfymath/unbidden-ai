from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from unbidden.sandbox.runner import SandboxError, SandboxRunner, SandboxSpec, docker_argv, snapshot

pytestmark = pytest.mark.unit


def test_docker_argv_is_offline_and_locked_down(tmp_path: Path) -> None:
    argv = docker_argv(SandboxSpec(image="img", argv=["tsc"]), tmp_path, "n")
    joined = " ".join(argv)
    for flag in ("--network none", "--read-only", "--cap-drop ALL", "no-new-privileges", "--user 1000:1000"):
        assert flag in joined
    assert argv[-2:] == ["img", "tsc"]


def test_network_other_than_none_is_refused(tmp_path: Path) -> None:
    spec = SandboxSpec(image="img", argv=["x"], network="host")  # type: ignore[arg-type]
    with pytest.raises(SandboxError):
        docker_argv(spec, tmp_path, "n")


def test_secrets_never_enter_a_sandbox(tmp_path: Path) -> None:
    spec = SandboxSpec(image="img", argv=["x"], env={"DB_PASSWORD": "hunter2hunter2"})
    with pytest.raises(SandboxError):
        SandboxRunner(docker="/bin/false").run(spec, tmp_path)


def test_snapshot_holds_only_tracked_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "app.py").write_text("x = 1\n")
    subprocess.run([*git, "add", "app.py"], check=True)
    subprocess.run([*git, "commit", "-qm", "init"], check=True)
    (repo / ".env").write_text("API_KEY=real\n")
    work = snapshot(repo, "HEAD", tmp_path / "work")
    assert (work / "app.py").read_text() == "x = 1\n"
    assert not (work / ".env").exists()
