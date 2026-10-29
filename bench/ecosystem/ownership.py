"""Who owns a lab resource, and the one way a lab tears down only its own (stage 9).

Every container, network and volume a lab creates carries two labels: the family (`unbidden.lab=ecosystem`, so a
person can list everything the labs made) and the lab's exact identity (`unbidden.lab.id=<lab>`). Teardown selects
by that identity alone, never by a name pattern and never by the family: in stage 8 a lab's `down` selected the
family and removed the containers of two other labs (Conduit's and LNbits'; their volumes were kept and both were
restored), and the fix that followed selected by a name prefix, which is still a broad match.

- Ordinary teardown keeps the lab's volumes (its data); removing them is explicit (`volumes=True`).
- Compose projects are torn down by their own project name (`docker compose -p`), never with `-v` unless explicit.
- Teardown tolerates what is already gone (a creation that failed halfway leaves only part of a lab) and reports
  what it could not remove (a network still used by a container of another lab) instead of forcing it.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

FAMILY = "unbidden.lab=ecosystem"
KEY = "unbidden.lab.id"


def labels(lab_id: str) -> list[str]:
    """`docker run`/`network create`/`volume create` arguments that mark a resource as this lab's."""
    return ["--label", FAMILY, "--label", f"{KEY}={lab_id}"]


def compose_labels(lab_id: str, indent: str = "      ") -> str:
    """The same marks for a compose service, network or volume (a `labels:` mapping's lines)."""
    family, value = FAMILY.split("=")
    return f'{indent}{family}: {value}\n{indent}{KEY}: "{lab_id}"\n'


def _docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=False)


def owned(kind: str, lab_id: str) -> list[str]:
    """Ids of this lab's resources of one kind: `container`, `network` or `volume`."""
    listing = {"container": ("ps", "-aq"), "network": ("network", "ls", "-q"), "volume": ("volume", "ls", "-q")}
    out = _docker(*listing[kind], "--filter", f"label={KEY}={lab_id}")
    return out.stdout.split() if out.returncode == 0 else []


@dataclass
class Teardown:
    lab_id: str
    removed: dict[str, list[str]] = field(default_factory=dict[str, list[str]])
    kept: dict[str, list[str]] = field(default_factory=dict[str, list[str]])  # volumes, unless asked
    failed: list[str] = field(default_factory=list[str])


def down(lab_id: str, *, volumes: bool = False) -> Teardown:
    """Remove this lab's containers and networks, and its volumes only when asked; nothing of any other lab."""
    report = Teardown(lab_id)
    for kind, remove in (("container", ("rm", "-f")), ("network", ("network", "rm")), ("volume", ("volume", "rm"))):
        ids = owned(kind, lab_id)
        if kind == "volume" and not volumes:
            report.kept[kind] = ids
            continue
        report.removed[kind] = []
        for rid in ids:
            done = _docker(*remove, rid)
            if done.returncode == 0:
                report.removed[kind].append(rid)
            else:
                report.failed.append(f"{kind} {rid}: {done.stderr.strip()[:200]}")
    return report


def compose_down(project: str, cwd: str, *, volumes: bool = False) -> int:
    """A compose project, by its own name; its volumes only when asked."""
    argv = ["docker", "compose", "-p", project, "down", *(["-v"] if volumes else [])]
    return subprocess.run(argv, cwd=cwd, capture_output=True, check=False).returncode
