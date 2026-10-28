"""A compose project started under another name (`docker compose -p staging up`) is still this repository's."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from unbidden.world import runtime

pytestmark = pytest.mark.unit


def test_containers_started_here_under_another_project_name_are_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "boardapp"
    repo.mkdir()
    calls: list[list[str]] = []

    def fake(argv: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        if argv[:2] == ["docker", "ps"]:
            assert f"label=com.docker.compose.project.working_dir={repo.resolve()}" in argv
            return subprocess.CompletedProcess(argv, 0, "boardapp-staging\nboardapp-staging\n", "")
        if argv[3] == "boardapp-staging":
            return subprocess.CompletedProcess(argv, 0, '{"Name": "boardapp-staging-board-1", "Publishers": []}\n', "")
        return subprocess.CompletedProcess(argv, 0, "", "")  # the derived name, `boardapp`, runs nothing

    monkeypatch.setattr(runtime.subprocess, "run", fake)
    assert [c["Name"] for c in runtime.running_containers(repo)] == ["boardapp-staging-board-1"]
    assert [c[3] for c in calls if c[:2] == ["docker", "compose"]] == ["boardapp", "boardapp-staging"]
