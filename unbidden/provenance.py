"""What produced a measurement: Unbidden's own code, the models it could call, and the environment it measured in.

Recorded on every experiment, so a verdict can be traced to the exact code and configuration that reached it, and
two verdicts can be told apart when either changed between them.
"""

from __future__ import annotations

import functools
import subprocess
from pathlib import Path
from typing import Any

from unbidden import __version__

PACKAGE = Path(__file__).resolve().parent


@functools.cache
def code_version() -> dict[str, Any]:
    """Unbidden's commit and whether its package differs from it, read once per process (never changes under it)."""
    git = ["git", "-C", str(PACKAGE)]
    commit = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=False).stdout.strip()
    dirty = subprocess.run(
        [*git, "status", "--porcelain", "--", str(PACKAGE)], capture_output=True, text=True, check=False
    ).stdout
    return {"version": __version__, "commit": commit or None, "dirty": bool(dirty.strip()) if commit else None}


def provenance(brain: Any, images: list[Any], **extra: Any) -> dict[str, Any]:
    """Code, model configuration and environment of one experiment. `extra` adds what the lab knows (a seed, a
    workload digest, the interpreter)."""
    routes: dict[str, str] = {}
    models: dict[str, Any] = {}
    if brain is not None:
        routes = {tier.value: f"{r.provider}:{r.model}:think={r.think}" for tier, r in brain.config.routing.items()}
        policy = brain.mandate.models
        models = {"profile": policy.profile, "local_fallback": policy.local_fallback,
                  "private_code_to_frontier": policy.private_code_to_frontier}  # fmt: skip
    return {
        "unbidden": code_version(),
        "routes": routes,
        "models": models,
        "images": sorted({i.tag for i in images if i is not None}),
        **{k: v for k, v in extra.items() if v is not None},
    }
