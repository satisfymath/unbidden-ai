"""A lab tears down only its own resources (stage 9). In stage 8 a lab's `down` selected the shared family label and
removed two other labs' containers; the next fix selected by a name prefix. Here, with real Docker: two labs side by
side, foreign resources (one unlabelled, one with the family label but another lab's identity), volumes, a creation
that failed halfway, and a network still used by another lab's container."""

from __future__ import annotations

import shutil
import subprocess
import uuid
from collections.abc import Iterator

import pytest

from bench.ecosystem import ownership

pytestmark = [pytest.mark.docker]
IMAGE = "python:3.12-slim"


def docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=False)


def available() -> bool:
    return shutil.which("docker") is not None and docker("image", "inspect", IMAGE).returncode == 0


@pytest.fixture
def world() -> Iterator[dict[str, str]]:
    if not available():
        pytest.skip(f"no Docker daemon, or no local {IMAGE}")
    tag = uuid.uuid4().hex[:8]
    names = {k: f"t-own-{tag}-{k}" for k in ("alpha", "beta", "foreign", "cousin", "gamma")}
    made: list[tuple[str, str]] = []

    def lab(key: str, lab_id: str | None) -> None:
        marks = ownership.labels(lab_id) if lab_id else []
        if lab_id == "cousin":  # the family label, another lab's identity
            marks = ["--label", ownership.FAMILY, "--label", f"{ownership.KEY}=t-other-{tag}"]
        docker("network", "create", *marks, names[key])
        docker("volume", "create", *marks, names[key])
        docker("run", "-d", "--name", names[key], *marks, "--network", names[key], "-v", f"{names[key]}:/data",
               IMAGE, "sleep", "300")  # fmt: skip
        made.extend([("container", names[key]), ("network", names[key]), ("volume", names[key])])

    lab("alpha", f"t-alpha-{tag}")
    lab("beta", f"t-beta-{tag}")
    lab("foreign", None)
    lab("cousin", "cousin")
    # gamma: a creation that failed halfway (network and volume made, the container never started)
    gamma = ownership.labels(f"t-gamma-{tag}")
    docker("network", "create", *gamma, names["gamma"])
    docker("volume", "create", *gamma, names["gamma"])
    made.extend([("network", names["gamma"]), ("volume", names["gamma"])])
    yield {"tag": tag, **names}
    # Containers first, then networks, then volumes: a network still serving a container cannot go, and the leaked
    # networks exhausted Docker's address pools (each run left one; seventeen runs, no network could be created).
    for wanted in ("container", "network", "volume"):
        for kind, name in made:
            if kind == wanted:
                docker(*({"container": ("rm", "-f"), "network": ("network", "rm"), "volume": ("volume", "rm")}[kind]),
                       name)  # fmt: skip
    assert not docker("network", "ls", "-q", "--filter", f"name=^t-own-{tag}").stdout.strip(), "a network leaked"


def exists(kind: str, name: str) -> bool:
    return docker(*({"container": ("container",), "network": ("network",), "volume": ("volume",)}[kind]),
                  "inspect", name).returncode == 0  # fmt: skip


def test_down_removes_only_its_lab_and_keeps_volumes_unless_asked(world: dict[str, str]) -> None:
    tag = world["tag"]
    report = ownership.down(f"t-alpha-{tag}")
    assert not report.failed
    assert not exists("container", world["alpha"]) and not exists("network", world["alpha"])
    assert exists("volume", world["alpha"])  # ordinary teardown keeps the data
    for other in ("beta", "foreign", "cousin"):  # the other lab, an unlabelled one, a family member
        assert all(exists(kind, world[other]) for kind in ("container", "network", "volume")), other
    ownership.down(f"t-alpha-{tag}", volumes=True)
    assert not exists("volume", world["alpha"]) and exists("volume", world["beta"])


def test_a_lab_created_halfway_is_torn_down_and_a_shared_network_is_reported_not_forced(
    world: dict[str, str],
) -> None:
    tag = world["tag"]
    assert not ownership.down(f"t-gamma-{tag}").failed  # no container: nothing to fail on
    assert not exists("network", world["gamma"]) and exists("volume", world["gamma"])
    assert ownership.down(f"t-gamma-{tag}").removed == {"container": [], "network": []}  # already gone: no error
    # beta's network also serves a container of another lab: beta's teardown says so and leaves it
    docker("network", "connect", world["beta"], world["foreign"])
    report = ownership.down(f"t-beta-{tag}")
    assert not exists("container", world["beta"]) and exists("container", world["foreign"])
    assert exists("network", world["beta"]) and any("network" in f for f in report.failed)
