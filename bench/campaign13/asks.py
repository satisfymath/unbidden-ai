"""The agent's questions during autonomous runs, answered by the fixed table of docs/bench/campaign13/PROTOCOL.md §7.

The harness gives the agent no other help. Every answer is recorded in the run as an automatic intervention with the
rule that produced it; a question the table does not cover is answered `later` and recorded as unanswered. Values
(credentials) travel on stdin from the campaign inventory, never in argv or a record."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bench.campaign13.common import run, unbidden

REGISTRIES = ("pypi.org", "files.pythonhosted.org", "deb.debian.org", "registry.npmjs.org", "ghcr.io",
              "registry-1.docker.io", "github.com", "objects.githubusercontent.com")  # fmt: skip
FINAL_CAP_USD = 5.0


@dataclass
class Policy:
    mode: str  # "autonomous" or "autopilot"
    lab: bool  # the repository has a lab (deploy steps, drill)
    credentials: dict[str, str] = field(default_factory=dict[str, str])  # name -> value, from the inventory
    answered: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

    def decide(self, ask: dict[str, Any]) -> tuple[str, str | None, str]:
        """(option, value, rule) for one open ask."""
        kind = ask.get("kind")
        options = {o.get("key") for o in ask.get("options") or []}
        title = str(ask.get("title", ""))
        if kind == "registry" and "allow" in options:
            hosts = [h.strip(" ?") for h in title.split("reach", 1)[-1].split(",")]
            if all(h in REGISTRIES for h in hosts if h):
                return "allow", None, "registry in the campaign list"
            return "later", None, "registry outside the campaign list"
        if kind == "credential" and "set" in options:
            value = self.credentials.get("MODEL_API_KEY")
            return ("set", value, "the campaign's model key") if value else ("later", None, "no such credential")
        if kind in ("capability", "access") and "approve" in options:
            return ("approve", None, "capability for a lab connection") if self.lab else ("later", None, "no lab")
        if kind == "approval" and "approve" in options:
            return ("approve", None, "autopilot: pull requests approved") if self.mode == "autopilot" else (
                "later", None, "autonomous opens pull requests itself")  # fmt: skip
        if kind == "deploy_steps" and "adopt" in options:
            return ("adopt", None, "the lab's procedure") if self.lab else ("skip", None, "no lab")
        if kind == "drill" and "run" in options:
            return ("run", None, "lab repository") if self.lab else ("later", None, "no lab")
        if kind == "spend" and "raise" in options:
            return "raise", f"{FINAL_CAP_USD:.2f}", "raise to the final pass's per-repository cap"
        if kind == "hold":
            return "keep", None, "a hold is kept: the product's own investigation is what is measured"
        if kind == "resume":
            return "later", None, "the kill switch is a person's; never released by the harness"
        return "later", None, "not covered by the table"


def answer_open(repo_dir: Path, env: dict[str, str], policy: Policy) -> list[dict[str, Any]]:
    """Answer every open ask once by the policy; return what was answered this pass."""
    listed = run("asks", [unbidden(), "ask", "--json"], cwd=repo_dir, env_=env, timeout_s=60)
    try:
        asks = json.loads(listed.stdout or "[]")
    except ValueError:
        return []
    done: list[dict[str, Any]] = []
    for ask in asks if isinstance(asks, list) else []:
        if any(a["id"] == ask.get("id") for a in policy.answered):
            continue
        option, value, rule = policy.decide(ask)
        argv = [unbidden(), "ask", str(ask["id"]), option, "--json"]
        stdin = None
        if value is not None and ask.get("kind") in ("credential", "connection"):
            argv.append("--value-stdin")
            stdin = value + "\n"
        elif value is not None:
            argv += ["--value", value]
        step = run(f"ask-{ask.get('kind')}", argv, cwd=repo_dir, env_=env, timeout_s=300, stdin=stdin)
        entry = {"id": ask.get("id"), "kind": ask.get("kind"), "title": str(ask.get("title", ""))[:160],
                 "answer": option, "rule": rule, "code": step.code}  # fmt: skip
        policy.answered.append(entry)
        done.append(entry)
    return done
